"""NVIDIA GPU detection for Docker containers."""

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)


def detect_gpu() -> bool:
    """Check if NVIDIA GPU and Docker GPU runtime are available.

    Returns True if both nvidia-smi succeeds and Docker has GPU support.
    Falls back to False with a warning if either check fails.
    """
    if not _check_nvidia_smi():
        return False
    if not _check_docker_gpu_runtime():
        return False
    return True


def _check_nvidia_smi() -> bool:
    """Check if nvidia-smi is available and reports a GPU."""
    if not shutil.which("nvidia-smi"):
        logger.debug("nvidia-smi not found in PATH")
        return False
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            logger.debug("GPU detected: %s", result.stdout.strip().split("\n")[0])
            return True
        logger.debug("nvidia-smi returned no GPUs")
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug("nvidia-smi check failed: %s", e)
        return False


def _check_docker_gpu_runtime() -> bool:
    """Check if Docker supports GPU via nvidia runtime."""
    docker_path = shutil.which("docker")
    if not docker_path:
        logger.debug("docker not found in PATH")
        return False
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.Runtimes}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and "nvidia" in result.stdout.lower():
            logger.debug("Docker nvidia runtime available")
            return True
        # Also check for default GPU support (newer Docker versions)
        result2 = subprocess.run(
            ["docker", "info", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result2.returncode == 0 and "nvidia" in result2.stdout.lower():
            logger.debug("Docker nvidia support detected via docker info")
            return True
        logger.debug("Docker nvidia runtime not found")
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug("Docker GPU runtime check failed: %s", e)
        return False
