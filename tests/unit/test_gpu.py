"""Tests for ai_shell.gpu module."""

from unittest.mock import MagicMock, patch

from ai_shell.gpu import (
    _check_docker_gpu_runtime,
    _check_nvidia_smi,
    detect_gpu,
    get_vram_info,
    get_vram_processes,
)


class TestDetectGpu:
    def test_returns_true_when_both_checks_pass(self):
        with (
            patch("ai_shell.gpu._check_nvidia_smi", return_value=True),
            patch("ai_shell.gpu._check_docker_gpu_runtime", return_value=True),
        ):
            assert detect_gpu() is True

    def test_returns_false_when_no_nvidia_smi(self):
        with (
            patch("ai_shell.gpu._check_nvidia_smi", return_value=False),
            patch("ai_shell.gpu._check_docker_gpu_runtime", return_value=True),
        ):
            assert detect_gpu() is False

    def test_returns_false_when_no_docker_gpu(self):
        with (
            patch("ai_shell.gpu._check_nvidia_smi", return_value=True),
            patch("ai_shell.gpu._check_docker_gpu_runtime", return_value=False),
        ):
            assert detect_gpu() is False


class TestCheckNvidiaSmi:
    def test_returns_false_when_not_in_path(self):
        with patch("ai_shell.gpu.shutil.which", return_value=None):
            assert _check_nvidia_smi() is False

    def test_returns_true_with_gpu_output(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "NVIDIA GeForce RTX 4090\n"

        with (
            patch("ai_shell.gpu.shutil.which", return_value="/usr/bin/nvidia-smi"),
            patch("ai_shell.gpu.subprocess.run", return_value=mock_result),
        ):
            assert _check_nvidia_smi() is True

    def test_returns_false_on_empty_output(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with (
            patch("ai_shell.gpu.shutil.which", return_value="/usr/bin/nvidia-smi"),
            patch("ai_shell.gpu.subprocess.run", return_value=mock_result),
        ):
            assert _check_nvidia_smi() is False

    def test_returns_false_on_error(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with (
            patch("ai_shell.gpu.shutil.which", return_value="/usr/bin/nvidia-smi"),
            patch("ai_shell.gpu.subprocess.run", return_value=mock_result),
        ):
            assert _check_nvidia_smi() is False


class TestGetVramInfo:
    def test_returns_none_when_nvidia_smi_not_found(self):
        with patch("ai_shell.gpu.shutil.which", return_value=None):
            assert get_vram_info() is None

    def test_returns_bytes_on_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "24564, 20000, 4564\n"

        with (
            patch("ai_shell.gpu.shutil.which", return_value="/usr/bin/nvidia-smi"),
            patch("ai_shell.gpu.subprocess.run", return_value=mock_result),
        ):
            info = get_vram_info()

        assert info is not None
        assert info["total"] == 24564 * 1024 * 1024
        assert info["free"] == 20000 * 1024 * 1024
        assert info["used"] == 4564 * 1024 * 1024

    def test_uses_first_gpu_when_multiple(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "24564, 20000, 4564\n8192, 6000, 2192\n"

        with (
            patch("ai_shell.gpu.shutil.which", return_value="/usr/bin/nvidia-smi"),
            patch("ai_shell.gpu.subprocess.run", return_value=mock_result),
        ):
            info = get_vram_info()

        assert info is not None
        assert info["total"] == 24564 * 1024 * 1024

    def test_returns_none_on_subprocess_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with (
            patch("ai_shell.gpu.shutil.which", return_value="/usr/bin/nvidia-smi"),
            patch("ai_shell.gpu.subprocess.run", return_value=mock_result),
        ):
            assert get_vram_info() is None

    def test_returns_none_on_unexpected_format(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not, valid\n"

        with (
            patch("ai_shell.gpu.shutil.which", return_value="/usr/bin/nvidia-smi"),
            patch("ai_shell.gpu.subprocess.run", return_value=mock_result),
        ):
            assert get_vram_info() is None


class TestGetVramProcesses:
    def test_returns_empty_when_nvidia_smi_not_found(self):
        with patch("ai_shell.gpu.shutil.which", return_value=None):
            assert get_vram_processes() == []

    def test_returns_empty_on_no_output(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with (
            patch("ai_shell.gpu.shutil.which", return_value="/usr/bin/nvidia-smi"),
            patch("ai_shell.gpu.subprocess.run", return_value=mock_result),
        ):
            assert get_vram_processes() == []

    def test_parses_process_list(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "12345, 2100, chrome\n67890, 4500, ollama\n"

        with (
            patch("ai_shell.gpu.shutil.which", return_value="/usr/bin/nvidia-smi"),
            patch("ai_shell.gpu.subprocess.run", return_value=mock_result),
        ):
            procs = get_vram_processes()

        assert len(procs) == 2
        assert procs[0] == (12345, 2100, "chrome")
        assert procs[1] == (67890, 4500, "ollama")

    def test_skips_malformed_lines(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "12345, 2100, chrome\nbad line\n67890, 4500, ollama\n"

        with (
            patch("ai_shell.gpu.shutil.which", return_value="/usr/bin/nvidia-smi"),
            patch("ai_shell.gpu.subprocess.run", return_value=mock_result),
        ):
            procs = get_vram_processes()

        assert len(procs) == 2


class TestCheckDockerGpuRuntime:
    def test_returns_false_when_docker_not_in_path(self):
        with patch("ai_shell.gpu.shutil.which", return_value=None):
            assert _check_docker_gpu_runtime() is False

    def test_returns_true_when_nvidia_in_runtimes(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "map[io.containerd.runc.v2:nvidia runc]"

        with (
            patch("ai_shell.gpu.shutil.which", return_value="/usr/bin/docker"),
            patch("ai_shell.gpu.subprocess.run", return_value=mock_result),
        ):
            assert _check_docker_gpu_runtime() is True

    def test_returns_false_when_no_nvidia_runtime(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "map[io.containerd.runc.v2 runc]"

        mock_result2 = MagicMock()
        mock_result2.returncode = 0
        mock_result2.stdout = '{"Runtimes": {"runc": {}}}'

        with (
            patch("ai_shell.gpu.shutil.which", return_value="/usr/bin/docker"),
            patch("ai_shell.gpu.subprocess.run", side_effect=[mock_result, mock_result2]),
        ):
            assert _check_docker_gpu_runtime() is False
