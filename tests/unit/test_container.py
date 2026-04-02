"""Tests for ai_shell.container module."""

from unittest.mock import MagicMock, patch

import pytest

from ai_shell.config import AiShellConfig
from ai_shell.defaults import SHM_SIZE
from ai_shell.exceptions import ContainerNotFoundError, DockerNotAvailableError, ImagePullError


class TestContainerManagerInit:
    def test_raises_when_docker_unavailable(self):
        with patch("ai_shell.container.docker") as mock_docker:
            mock_docker.from_env.side_effect = Exception("Connection refused")
            mock_docker.errors.DockerException = Exception

            with pytest.raises(DockerNotAvailableError):
                from ai_shell.container import ContainerManager

                ContainerManager(AiShellConfig())


class TestEnsureDevContainer:
    def test_creates_new_container(self, mock_container_manager, mock_docker_client):
        mock_docker_client.containers.get.side_effect = Exception("not found")

        # Mock NotFound exception
        with patch("ai_shell.container.NotFound", Exception):
            mock_container_manager._get_container = MagicMock(return_value=None)
            mock_container_manager._pull_image_if_needed = MagicMock()
            mock_docker_client.containers.run.return_value = MagicMock()

            name = mock_container_manager.ensure_dev_container()

        assert name == "augint-shell-test-project-dev"
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

    def test_starts_existing_stopped_container(self, mock_container_manager):
        stopped_container = MagicMock()
        stopped_container.status = "exited"
        mock_container_manager._get_container = MagicMock(return_value=stopped_container)

        name = mock_container_manager.ensure_dev_container()

        stopped_container.start.assert_called_once()
        assert name == "augint-shell-test-project-dev"

    def test_reuses_running_container(self, mock_container_manager):
        running_container = MagicMock()
        running_container.status = "running"
        mock_container_manager._get_container = MagicMock(return_value=running_container)

        name = mock_container_manager.ensure_dev_container()

        running_container.start.assert_not_called()
        assert name == "augint-shell-test-project-dev"


class TestExecInteractive:
    def test_builds_correct_docker_args(self, mock_container_manager):
        with patch("ai_shell.container.os.execvp") as mock_execvp:
            mock_container_manager.exec_interactive(
                "augint-shell-test-dev",
                ["claude", "--debug"],
            )

            mock_execvp.assert_called_once_with(
                "docker",
                ["docker", "exec", "-it", "augint-shell-test-dev", "claude", "--debug"],
            )

    def test_passes_extra_env(self, mock_container_manager):
        with patch("ai_shell.container.os.execvp") as mock_execvp:
            mock_container_manager.exec_interactive(
                "augint-shell-test-dev",
                ["aider"],
                extra_env={"OLLAMA_API_BASE": "http://host.docker.internal:11434"},
            )

            args = mock_execvp.call_args[0][1]
            assert "-e" in args
            env_idx = args.index("-e")
            assert args[env_idx + 1] == "OLLAMA_API_BASE=http://host.docker.internal:11434"


class TestEnsureOllama:
    def test_creates_with_gpu_when_available(self, mock_container_manager, mock_docker_client):
        mock_container_manager._get_container = MagicMock(return_value=None)
        mock_container_manager._pull_image_if_needed = MagicMock()

        with patch("ai_shell.container.detect_gpu", return_value=True):
            mock_container_manager.ensure_ollama()

        call_kwargs = mock_docker_client.containers.run.call_args[1]
        assert "device_requests" in call_kwargs
        assert len(call_kwargs["device_requests"]) == 1

    def test_creates_without_gpu_when_unavailable(self, mock_container_manager, mock_docker_client):
        mock_container_manager._get_container = MagicMock(return_value=None)
        mock_container_manager._pull_image_if_needed = MagicMock()

        with patch("ai_shell.container.detect_gpu", return_value=False):
            mock_container_manager.ensure_ollama()

        call_kwargs = mock_docker_client.containers.run.call_args[1]
        assert "device_requests" not in call_kwargs


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

    def test_remove_container(self, mock_container_manager):
        container = MagicMock()
        mock_container_manager._get_container = MagicMock(return_value=container)

        mock_container_manager.remove_container("test", force=True)
        container.remove.assert_called_once_with(force=True)

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

    def test_starts_stopped_webui(self, mock_container_manager):
        stopped = MagicMock()
        stopped.status = "exited"
        mock_container_manager._get_container = MagicMock(return_value=stopped)

        name = mock_container_manager.ensure_webui()
        stopped.start.assert_called_once()
        assert name == "augint-shell-webui"


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


class TestContainerLogs:
    def test_prints_logs(self, mock_container_manager):
        container = MagicMock()
        container.logs.return_value = b"log output here"
        mock_container_manager._get_container = MagicMock(return_value=container)

        mock_container_manager.container_logs("test", follow=False)
        container.logs.assert_called_once_with(tail=100)

    def test_raises_for_missing_container(self, mock_container_manager):
        mock_container_manager._get_container = MagicMock(return_value=None)

        with pytest.raises(ContainerNotFoundError):
            mock_container_manager.container_logs("missing", follow=False)


class TestPullImage:
    def test_skips_when_image_exists(self, mock_container_manager, mock_docker_client):
        mock_docker_client.images.get.return_value = MagicMock()
        mock_container_manager._pull_image_if_needed("test:latest")
        mock_docker_client.images.pull.assert_not_called()

    def test_pulls_when_image_missing(self, mock_container_manager, mock_docker_client):
        from docker.errors import ImageNotFound

        mock_docker_client.images.get.side_effect = ImageNotFound("not found")
        mock_container_manager._pull_image_if_needed("test:latest")
        mock_docker_client.images.pull.assert_called_once_with("test", "latest")


class TestExtraVolumes:
    def test_extra_volumes_from_config(self, mock_docker_client):
        with patch("ai_shell.container.docker") as mock_docker:
            mock_docker.from_env.return_value = mock_docker_client
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
