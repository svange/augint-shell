"""Tests for ai_shell.gpu module."""

from unittest.mock import MagicMock, patch

from ai_shell.gpu import _check_docker_gpu_runtime, _check_nvidia_smi, detect_gpu


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
