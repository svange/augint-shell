"""Tests for ai_shell.container module."""

from unittest.mock import MagicMock, patch

import pytest

from ai_shell.config import AiShellConfig
from ai_shell.defaults import DEFAULT_DEV_PORTS, LLM_NETWORK, SHM_SIZE
from ai_shell.exceptions import ContainerNotFoundError, DockerNotAvailableError, ImagePullError


class TestContainerManagerInit:
    def test_raises_when_docker_unavailable(self):
        with patch("ai_shell.container.docker") as mock_docker:
            mock_docker.from_env.side_effect = Exception("Connection refused")
            mock_docker.errors.DockerException = Exception

            with pytest.raises(DockerNotAvailableError):
                from ai_shell.container import ContainerManager

                ContainerManager(AiShellConfig())


class TestResolveDevContainer:
    def test_returns_current_name_when_found(self, mock_container_manager):
        container = MagicMock()
        mock_container_manager._get_container = MagicMock(return_value=container)

        name, result = mock_container_manager.resolve_dev_container()

        assert name.startswith("augint-shell-test-project-")
        assert name.endswith("-dev")
        assert name != "augint-shell-test-project-dev"  # has hash
        assert result is container

    def test_falls_back_to_legacy_when_mount_matches(self, mock_container_manager):
        legacy_container = MagicMock()
        legacy_container.attrs = {
            "Mounts": [{"Source": str(mock_container_manager.config.project_dir.resolve())}]
        }

        def get_container(name):
            if name == "augint-shell-test-project-dev":
                return legacy_container
            return None

        mock_container_manager._get_container = MagicMock(side_effect=get_container)

        name, result = mock_container_manager.resolve_dev_container()

        assert name == "augint-shell-test-project-dev"
        assert result is legacy_container

    def test_ignores_legacy_when_mount_mismatches(self, mock_container_manager):
        legacy_container = MagicMock()
        legacy_container.attrs = {"Mounts": [{"Source": "/other/path"}]}
        mock_container_manager._get_container = MagicMock(side_effect=[None, legacy_container])

        name, result = mock_container_manager.resolve_dev_container()

        assert name.startswith("augint-shell-test-project-")
        assert name != "augint-shell-test-project-dev"
        assert result is None

    def test_returns_none_when_neither_exists(self, mock_container_manager):
        mock_container_manager._get_container = MagicMock(return_value=None)

        name, result = mock_container_manager.resolve_dev_container()

        assert name.startswith("augint-shell-test-project-")
        assert name.endswith("-dev")
        assert result is None


class TestEnsureDevContainer:
    def test_creates_new_container(self, mock_container_manager, mock_docker_client):
        mock_docker_client.containers.get.side_effect = Exception("not found")

        # Mock NotFound exception
        with patch("ai_shell.container.NotFound", Exception):
            mock_container_manager._get_container = MagicMock(return_value=None)
            mock_container_manager._pull_image_if_needed = MagicMock()
            mock_docker_client.containers.run.return_value = MagicMock()

            name = mock_container_manager.ensure_dev_container()

        assert name.startswith("augint-shell-test-project-")
        assert name.endswith("-dev")
        mock_docker_client.containers.run.assert_called_once()

        # Verify critical docker-compose config
        call_kwargs = mock_docker_client.containers.run.call_args[1]
        assert call_kwargs["shm_size"] == SHM_SIZE
        assert call_kwargs["init"] is True
        assert call_kwargs["stdin_open"] is True
        assert call_kwargs["tty"] is True
        assert call_kwargs["working_dir"] == "/root/projects/test-project"
        assert call_kwargs["command"] == "tail -f /dev/null"
        assert call_kwargs["extra_hosts"] == {"host.docker.internal": "host-gateway"}
        assert call_kwargs["detach"] is True

        # Verify all default dev ports are exposed with ephemeral host mapping
        expected_ports = {f"{port}/tcp": None for port in sorted(DEFAULT_DEV_PORTS)}
        assert call_kwargs["ports"] == expected_ports

    def test_creates_container_with_extra_ports(self, mock_docker_client):
        with patch("ai_shell.container.docker") as mock_docker:
            mock_docker.from_env.return_value = mock_docker_client
            mock_docker.errors = MagicMock()
            mock_docker.errors.DockerException = Exception

            from ai_shell.container import ContainerManager

            config = AiShellConfig(
                project_name="test-project",
                extra_ports=[9000, 9229],
            )
            manager = ContainerManager(config)
            manager._get_container = MagicMock(return_value=None)
            manager._pull_image_if_needed = MagicMock()

            manager.ensure_dev_container()

            call_kwargs = mock_docker_client.containers.run.call_args[1]
            assert "9000/tcp" in call_kwargs["ports"]
            assert "9229/tcp" in call_kwargs["ports"]
            # Default ports still present
            assert "3000/tcp" in call_kwargs["ports"]
            assert "8000/tcp" in call_kwargs["ports"]

    def test_starts_existing_stopped_container(self, mock_container_manager):
        stopped_container = MagicMock()
        stopped_container.status = "exited"
        mock_container_manager._get_container = MagicMock(return_value=stopped_container)

        name = mock_container_manager.ensure_dev_container()

        stopped_container.start.assert_called_once()
        assert name.startswith("augint-shell-test-project-")
        assert name.endswith("-dev")

    def test_reuses_running_container(self, mock_container_manager):
        running_container = MagicMock()
        running_container.status = "running"
        mock_container_manager._get_container = MagicMock(return_value=running_container)

        name = mock_container_manager.ensure_dev_container()

        running_container.start.assert_not_called()
        assert name.startswith("augint-shell-test-project-")
        assert name.endswith("-dev")

    def test_reuses_matching_legacy_container(self, mock_container_manager):
        legacy_container = MagicMock()
        legacy_container.status = "running"
        legacy_container.attrs = {
            "Mounts": [{"Source": str(mock_container_manager.config.project_dir.resolve())}]
        }

        def get_container(name):
            if name == "augint-shell-test-project-dev":
                return legacy_container
            return None

        mock_container_manager._get_container = MagicMock(side_effect=get_container)

        name = mock_container_manager.ensure_dev_container()

        assert name == "augint-shell-test-project-dev"
        legacy_container.start.assert_not_called()

    def test_ignores_mismatched_legacy_container(self, mock_container_manager):
        legacy_container = MagicMock()
        legacy_container.status = "exited"
        legacy_container.attrs = {"Mounts": [{"Source": "/other/path"}]}
        mock_container_manager._get_container = MagicMock(side_effect=[None, legacy_container])
        mock_container_manager._pull_image_if_needed = MagicMock()
        mock_container_manager.client.containers.run.return_value = MagicMock()

        name = mock_container_manager.ensure_dev_container()

        assert name.startswith("augint-shell-test-project-")
        assert name.endswith("-dev")
        assert name != "augint-shell-test-project-dev"
        legacy_container.start.assert_not_called()


class TestExecInteractive:
    def test_builds_correct_docker_args(self, mock_container_manager):
        with (
            patch("ai_shell.container.subprocess.run") as mock_run,
            patch("ai_shell.container.sys.stdin") as mock_stdin,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            mock_stdin.isatty.return_value = True

            with pytest.raises(SystemExit) as exc_info:
                mock_container_manager.exec_interactive(
                    "augint-shell-test-dev",
                    ["claude", "--debug"],
                )

            mock_run.assert_called_once_with(
                ["docker", "exec", "-it", "augint-shell-test-dev", "claude", "--debug"],
            )
            assert exc_info.value.code == 0

    def test_passes_extra_env(self, mock_container_manager):
        with (
            patch("ai_shell.container.subprocess.run") as mock_run,
            patch("ai_shell.container.sys.stdin") as mock_stdin,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            mock_stdin.isatty.return_value = True

            with pytest.raises(SystemExit):
                mock_container_manager.exec_interactive(
                    "augint-shell-test-dev",
                    ["aider"],
                    extra_env={"OLLAMA_API_BASE": "http://host.docker.internal:11434"},
                )

            args = mock_run.call_args[0][0]
            assert "-e" in args
            env_idx = args.index("-e")
            assert args[env_idx + 1] == "OLLAMA_API_BASE=http://host.docker.internal:11434"

    def test_no_tty_flags_when_not_a_tty(self, mock_container_manager):
        with (
            patch("ai_shell.container.subprocess.run") as mock_run,
            patch("ai_shell.container.sys.stdin") as mock_stdin,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            mock_stdin.isatty.return_value = False

            with pytest.raises(SystemExit):
                mock_container_manager.exec_interactive(
                    "augint-shell-test-dev",
                    ["claude"],
                )

            args = mock_run.call_args[0][0]
            assert "-it" not in args

    def test_propagates_nonzero_exit_code(self, mock_container_manager):
        with (
            patch("ai_shell.container.subprocess.run") as mock_run,
            patch("ai_shell.container.sys.stdin") as mock_stdin,
        ):
            mock_run.return_value = MagicMock(returncode=130)
            mock_stdin.isatty.return_value = True

            with pytest.raises(SystemExit) as exc_info:
                mock_container_manager.exec_interactive(
                    "augint-shell-test-dev",
                    ["claude"],
                )

            assert exc_info.value.code == 130

    def test_passes_workdir(self, mock_container_manager):
        with (
            patch("ai_shell.container.subprocess.run") as mock_run,
            patch("ai_shell.container.sys.stdin") as mock_stdin,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            mock_stdin.isatty.return_value = True

            with pytest.raises(SystemExit):
                mock_container_manager.exec_interactive(
                    "augint-shell-test-dev",
                    ["claude"],
                    workdir="/root/projects/my-project/.claude/worktrees/feat",
                )

            args = mock_run.call_args[0][0]
            assert "-w" in args
            w_idx = args.index("-w")
            assert args[w_idx + 1] == "/root/projects/my-project/.claude/worktrees/feat"

    def test_no_workdir_omits_w_flag(self, mock_container_manager):
        with (
            patch("ai_shell.container.subprocess.run") as mock_run,
            patch("ai_shell.container.sys.stdin") as mock_stdin,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            mock_stdin.isatty.return_value = True

            with pytest.raises(SystemExit):
                mock_container_manager.exec_interactive(
                    "augint-shell-test-dev",
                    ["claude"],
                )

            args = mock_run.call_args[0][0]
            assert "-w" not in args


class TestRunInteractive:
    def test_returns_exit_code_and_elapsed(self, mock_container_manager):
        with (
            patch("ai_shell.container.subprocess.run") as mock_run,
            patch("ai_shell.container.sys.stdin") as mock_stdin,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            mock_stdin.isatty.return_value = True

            exit_code, elapsed = mock_container_manager.run_interactive(
                "augint-shell-test-dev",
                ["claude", "--dangerously-skip-permissions", "-c"],
            )

            assert exit_code == 0
            assert elapsed >= 0
            mock_run.assert_called_once_with(
                [
                    "docker",
                    "exec",
                    "-it",
                    "augint-shell-test-dev",
                    "claude",
                    "--dangerously-skip-permissions",
                    "-c",
                ],
            )

    def test_returns_nonzero_exit_code(self, mock_container_manager):
        with (
            patch("ai_shell.container.subprocess.run") as mock_run,
            patch("ai_shell.container.sys.stdin") as mock_stdin,
        ):
            mock_run.return_value = MagicMock(returncode=1)
            mock_stdin.isatty.return_value = True

            exit_code, elapsed = mock_container_manager.run_interactive(
                "augint-shell-test-dev",
                ["claude", "-c"],
            )

            assert exit_code == 1

    def test_passes_workdir(self, mock_container_manager):
        with (
            patch("ai_shell.container.subprocess.run") as mock_run,
            patch("ai_shell.container.sys.stdin") as mock_stdin,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            mock_stdin.isatty.return_value = True

            mock_container_manager.run_interactive(
                "augint-shell-test-dev",
                ["claude", "-c"],
                workdir="/root/projects/my-project/.claude/worktrees/feat",
            )

            args = mock_run.call_args[0][0]
            assert "-w" in args
            w_idx = args.index("-w")
            assert args[w_idx + 1] == "/root/projects/my-project/.claude/worktrees/feat"


class TestEnsureLlmNetwork:
    def test_creates_network_when_missing(self, mock_container_manager, mock_docker_client):
        # mock_docker_client.networks.get already raises NotFound via conftest
        mock_container_manager._ensure_llm_network()

        mock_docker_client.networks.create.assert_called_once_with(LLM_NETWORK, driver="bridge")

    def test_reuses_existing_network(self, mock_container_manager, mock_docker_client):
        # Override: network exists
        mock_docker_client.networks.get.side_effect = None
        mock_docker_client.networks.get.return_value = MagicMock()

        mock_container_manager._ensure_llm_network()

        mock_docker_client.networks.create.assert_not_called()


class TestEnsureOllama:
    def test_creates_with_gpu_when_available(self, mock_container_manager, mock_docker_client):
        mock_container_manager._get_container = MagicMock(return_value=None)
        mock_container_manager._pull_image_if_needed = MagicMock()

        with (
            patch("ai_shell.container.detect_gpu", return_value=True),
            patch("ai_shell.container.get_vram_info", return_value=None),
        ):
            mock_container_manager.ensure_ollama()

        call_kwargs = mock_docker_client.containers.run.call_args[1]
        assert "device_requests" in call_kwargs
        assert len(call_kwargs["device_requests"]) == 1
        assert call_kwargs["network"] == LLM_NETWORK

    def test_creates_without_gpu_when_unavailable(self, mock_container_manager, mock_docker_client):
        mock_container_manager._get_container = MagicMock(return_value=None)
        mock_container_manager._pull_image_if_needed = MagicMock()

        with (
            patch("ai_shell.container.detect_gpu", return_value=False),
            patch("ai_shell.container.get_vram_info", return_value=None),
        ):
            mock_container_manager.ensure_ollama()

        call_kwargs = mock_docker_client.containers.run.call_args[1]
        assert "device_requests" not in call_kwargs
        assert call_kwargs["network"] == LLM_NETWORK

    def test_sets_gpu_overhead_when_vram_info_available(
        self, mock_container_manager, mock_docker_client
    ):
        mock_container_manager._get_container = MagicMock(return_value=None)
        mock_container_manager._pull_image_if_needed = MagicMock()
        vram_info = {
            "total": 24 * 1024**3,
            "free": 20 * 1024**3,
            "used": 4 * 1024**3,
        }

        with (
            patch("ai_shell.container.detect_gpu", return_value=True),
            patch("ai_shell.container.get_vram_info", return_value=vram_info),
        ):
            mock_container_manager.ensure_ollama()

        call_kwargs = mock_docker_client.containers.run.call_args[1]
        assert "environment" in call_kwargs
        overhead = int(call_kwargs["environment"]["OLLAMA_GPU_OVERHEAD"])
        assert overhead == 4 * 1024**3 + 1 * 1024**3  # used + 1 GiB buffer

    def test_no_gpu_overhead_when_vram_info_unavailable(
        self, mock_container_manager, mock_docker_client
    ):
        mock_container_manager._get_container = MagicMock(return_value=None)
        mock_container_manager._pull_image_if_needed = MagicMock()

        with (
            patch("ai_shell.container.detect_gpu", return_value=True),
            patch("ai_shell.container.get_vram_info", return_value=None),
        ):
            mock_container_manager.ensure_ollama()

        call_kwargs = mock_docker_client.containers.run.call_args[1]
        # OLLAMA_CONTEXT_LENGTH is always set; GPU overhead is not
        assert call_kwargs["environment"].get("OLLAMA_CONTEXT_LENGTH")
        assert "OLLAMA_GPU_OVERHEAD" not in call_kwargs["environment"]

    def test_no_gpu_overhead_when_no_gpu(self, mock_container_manager, mock_docker_client):
        mock_container_manager._get_container = MagicMock(return_value=None)
        mock_container_manager._pull_image_if_needed = MagicMock()

        with (
            patch("ai_shell.container.detect_gpu", return_value=False),
            patch("ai_shell.container.get_vram_info", return_value=None),
        ):
            mock_container_manager.ensure_ollama()

        call_kwargs = mock_docker_client.containers.run.call_args[1]
        assert call_kwargs["environment"].get("OLLAMA_CONTEXT_LENGTH")
        assert "OLLAMA_GPU_OVERHEAD" not in call_kwargs["environment"]

    def test_always_sets_cpu_shares(self, mock_container_manager, mock_docker_client):
        mock_container_manager._get_container = MagicMock(return_value=None)
        mock_container_manager._pull_image_if_needed = MagicMock()

        with (
            patch("ai_shell.container.detect_gpu", return_value=False),
            patch("ai_shell.container.get_vram_info", return_value=None),
        ):
            mock_container_manager.ensure_ollama()

        call_kwargs = mock_docker_client.containers.run.call_args[1]
        assert call_kwargs["cpu_shares"] == 1024


class TestContainerLifecycle:
    def test_stop_running_container(self, mock_container_manager):
        container = MagicMock()
        container.status = "running"
        mock_container_manager._get_container = MagicMock(return_value=container)

        mock_container_manager.stop_container("test")
        container.stop.assert_called_once()

    def test_stop_nonexistent_raises(self, mock_container_manager):
        mock_container_manager._get_container = MagicMock(return_value=None)

        with pytest.raises(ContainerNotFoundError):
            mock_container_manager.stop_container("nonexistent")

    def test_remove_stopped_container(self, mock_container_manager):
        container = MagicMock()
        container.status = "exited"
        mock_container_manager._get_container = MagicMock(return_value=container)

        mock_container_manager.remove_container("test")
        container.stop.assert_not_called()
        container.remove.assert_called_once_with()

    def test_remove_running_container_stops_first(self, mock_container_manager):
        container = MagicMock()
        container.status = "running"
        mock_container_manager._get_container = MagicMock(return_value=container)

        mock_container_manager.remove_container("test")
        container.stop.assert_called_once()
        container.remove.assert_called_once_with()

    def test_remove_nonexistent_raises(self, mock_container_manager):
        mock_container_manager._get_container = MagicMock(return_value=None)

        with pytest.raises(ContainerNotFoundError):
            mock_container_manager.remove_container("nonexistent")

    def test_container_status_returns_none_for_missing(self, mock_container_manager):
        mock_container_manager._get_container = MagicMock(return_value=None)
        assert mock_container_manager.container_status("missing") is None

    def test_container_status_returns_status(self, mock_container_manager):
        container = MagicMock()
        container.status = "running"
        mock_container_manager._get_container = MagicMock(return_value=container)
        assert mock_container_manager.container_status("test") == "running"


class TestEnsureWebui:
    def test_creates_webui_container(self, mock_container_manager, mock_docker_client):
        mock_container_manager._get_container = MagicMock(return_value=None)
        mock_container_manager._pull_image_if_needed = MagicMock()

        name = mock_container_manager.ensure_webui()

        assert name == "augint-shell-webui"
        mock_docker_client.containers.run.assert_called_once()
        call_kwargs = mock_docker_client.containers.run.call_args[1]
        assert "OLLAMA_BASE_URL" in call_kwargs["environment"]
        assert call_kwargs["network"] == LLM_NETWORK
        assert "network_mode" not in call_kwargs

    def test_starts_stopped_webui(self, mock_container_manager):
        stopped = MagicMock()
        stopped.status = "exited"
        mock_container_manager._get_container = MagicMock(return_value=stopped)

        name = mock_container_manager.ensure_webui()
        stopped.start.assert_called_once()
        assert name == "augint-shell-webui"


class TestEnsureLobechat:
    def test_creates_lobechat_container(self, mock_container_manager, mock_docker_client):
        mock_container_manager._get_container = MagicMock(return_value=None)
        mock_container_manager._pull_image_if_needed = MagicMock()

        name = mock_container_manager.ensure_lobechat()

        assert name == "augint-shell-lobechat"
        mock_docker_client.containers.run.assert_called_once()
        call_kwargs = mock_docker_client.containers.run.call_args[1]
        assert call_kwargs["image"] == "lobehub/lobe-chat:latest"
        assert call_kwargs["name"] == "augint-shell-lobechat"
        assert "OLLAMA_PROXY_URL" in call_kwargs["environment"]
        assert call_kwargs["environment"]["OLLAMA_PROXY_URL"].endswith(":11434/v1")
        assert call_kwargs["network"] == LLM_NETWORK
        assert "network_mode" not in call_kwargs
        assert "mounts" not in call_kwargs  # client-DB mode, no server-side state

    def test_starts_stopped_lobechat(self, mock_container_manager):
        stopped = MagicMock()
        stopped.status = "exited"
        mock_container_manager._get_container = MagicMock(return_value=stopped)

        name = mock_container_manager.ensure_lobechat()
        stopped.start.assert_called_once()
        assert name == "augint-shell-lobechat"


class TestExecInOllama:
    def test_runs_command_and_returns_output(self, mock_container_manager):
        container = MagicMock()
        container.status = "running"
        container.exec_run.return_value = (0, b"model list output")
        mock_container_manager._get_container = MagicMock(return_value=container)

        result = mock_container_manager.exec_in_ollama(["ollama", "list"])
        assert result == "model list output"

    def test_raises_when_ollama_not_running(self, mock_container_manager):
        mock_container_manager._get_container = MagicMock(return_value=None)

        with pytest.raises(ContainerNotFoundError):
            mock_container_manager.exec_in_ollama(["ollama", "list"])


class TestContainerPorts:
    def test_returns_port_mappings(self, mock_container_manager):
        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Ports": {
                    "3000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "49152"}],
                    "8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "49153"}],
                    "5678/tcp": None,
                }
            }
        }
        mock_container_manager._get_container = MagicMock(return_value=container)

        result = mock_container_manager.container_ports("test")
        assert result == {
            "3000/tcp": "0.0.0.0:49152",
            "8000/tcp": "0.0.0.0:49153",
        }
        container.reload.assert_called_once()

    def test_returns_none_for_missing_container(self, mock_container_manager):
        mock_container_manager._get_container = MagicMock(return_value=None)
        assert mock_container_manager.container_ports("missing") is None


class TestContainerLogs:
    def test_prints_logs(self, mock_container_manager):
        container = MagicMock()
        container.logs.return_value = b"log output here"
        mock_container_manager._get_container = MagicMock(return_value=container)

        mock_container_manager.container_logs("test", follow=False)
        container.logs.assert_called_once_with(tail=100)

    def test_follow_mode_uses_docker_cli(self, mock_container_manager):
        with patch("ai_shell.container.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            with pytest.raises(SystemExit):
                mock_container_manager.container_logs("test", follow=True)

            mock_run.assert_called_once_with(
                ["docker", "logs", "-f", "test"],
            )

    def test_raises_for_missing_container(self, mock_container_manager):
        mock_container_manager._get_container = MagicMock(return_value=None)

        with pytest.raises(ContainerNotFoundError):
            mock_container_manager.container_logs("missing", follow=False)


class TestPullImage:
    def test_skips_when_versioned_image_exists(self, mock_container_manager, mock_docker_client):
        mock_docker_client.images.get.return_value = MagicMock()
        mock_container_manager._pull_image_if_needed("test:1.0.0")
        mock_docker_client.images.pull.assert_not_called()

    def test_pulls_when_versioned_image_missing(self, mock_container_manager, mock_docker_client):
        from docker.errors import ImageNotFound

        mock_docker_client.images.get.side_effect = ImageNotFound("not found")
        mock_container_manager._pull_image_if_needed("test:1.0.0")
        mock_docker_client.images.pull.assert_called_once_with("test", "1.0.0")

    def test_always_pulls_latest_tag(self, mock_container_manager, mock_docker_client):
        """Latest tag should always pull to ensure freshness."""
        mock_docker_client.images.get.return_value = MagicMock()
        mock_container_manager._pull_image_if_needed("test:latest")
        mock_docker_client.images.pull.assert_called_once_with("test", "latest")

    def test_latest_falls_back_to_cache_on_pull_failure(
        self, mock_container_manager, mock_docker_client
    ):
        """If pulling latest fails but a cached copy exists, use the cache."""
        from docker.errors import APIError

        mock_docker_client.images.pull.side_effect = APIError("network error")
        mock_docker_client.images.get.return_value = MagicMock()  # cached copy exists
        # Should not raise — falls back to cache
        mock_container_manager._pull_image_if_needed("test:latest")

    def test_latest_raises_when_no_cache_and_pull_fails(
        self, mock_container_manager, mock_docker_client
    ):
        """If pulling latest fails and no cached copy, raise ImagePullError."""
        from docker.errors import APIError, ImageNotFound

        mock_docker_client.images.pull.side_effect = APIError("network error")
        mock_docker_client.images.get.side_effect = ImageNotFound("not found")

        with pytest.raises(ImagePullError):
            mock_container_manager._pull_image_if_needed("test:latest")


class TestEnsureToolFresh:
    def test_skips_when_script_missing(self, mock_container_manager):
        """Should silently skip if update-tools.sh is not in the container."""
        with patch("ai_shell.container.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)  # test -x fails
            mock_container_manager.ensure_tool_fresh("test-container", "codex")

            # Only the existence check should be called
            mock_run.assert_called_once()
            assert "test" in mock_run.call_args[0][0]

    def test_skips_when_tool_is_fresh(self, mock_container_manager):
        """Should skip update when tool marker is within TTL."""
        with patch("ai_shell.container.subprocess.run") as mock_run:
            # First call: script exists (exit 0), second call: tool fresh (exit 0)
            mock_run.side_effect = [
                MagicMock(returncode=0),  # test -x
                MagicMock(returncode=0),  # --check (fresh)
            ]
            mock_container_manager.ensure_tool_fresh("test-container", "codex")
            assert mock_run.call_count == 2

    def test_updates_when_tool_is_stale(self, mock_container_manager):
        """Should run --tool update when tool marker is stale."""
        with patch("ai_shell.container.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0),  # test -x (exists)
                MagicMock(returncode=1),  # --check (stale)
                MagicMock(returncode=0),  # --tool (update)
            ]
            mock_container_manager.ensure_tool_fresh("test-container", "codex")
            assert mock_run.call_count == 3
            # Third call should be the update
            update_args = mock_run.call_args_list[2][0][0]
            assert "--tool" in update_args
            assert "codex" in update_args

    def test_continues_when_update_fails(self, mock_container_manager):
        """Should not raise when tool update returns non-zero."""
        with patch("ai_shell.container.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0),  # test -x
                MagicMock(returncode=1),  # --check (stale)
                MagicMock(returncode=1),  # --tool (failed)
            ]
            # Should not raise
            mock_container_manager.ensure_tool_fresh("test-container", "codex")


class TestExtraVolumes:
    def test_extra_volumes_from_config(self, mock_docker_client):
        with patch("ai_shell.container.docker") as mock_docker:
            mock_docker.from_env.return_value = mock_docker_client
            mock_docker.errors = MagicMock()
            mock_docker.errors.DockerException = Exception

            from ai_shell.container import ContainerManager

            config = AiShellConfig(
                project_name="test",
                extra_volumes=["/host/path:/container/path:ro"],
            )
            manager = ContainerManager(config)
            manager._get_container = MagicMock(return_value=None)
            manager._pull_image_if_needed = MagicMock()

            manager.ensure_dev_container()

            call_kwargs = mock_docker_client.containers.run.call_args[1]
            mounts = call_kwargs["mounts"]
            targets = [m.get("Target") for m in mounts]
            assert "/container/path" in targets


class TestExceptions:
    def test_image_pull_error(self):
        err = ImagePullError("my-image:latest", "network timeout")
        assert "my-image:latest" in str(err)
        assert "network timeout" in str(err)
        assert err.image == "my-image:latest"

    def test_container_not_found_error(self):
        err = ContainerNotFoundError("my-container")
        assert "my-container" in str(err)
        assert err.name == "my-container"
