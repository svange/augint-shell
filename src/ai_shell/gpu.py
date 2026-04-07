"""NVIDIA GPU detection for Docker containers."""

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

_MIB = 1024 * 1024


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


def get_vram_info() -> dict[str, int] | None:
    """Query current GPU VRAM usage.

    Returns dict with keys total/free/used in bytes, or None if unavailable.
    Uses the first GPU reported by nvidia-smi.
    """
    if not shutil.which("nvidia-smi"):
        return None
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total,memory.free,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        line = result.stdout.strip().split("\n")[0]
        parts = line.split(",")
        if len(parts) != 3:
            return None
        total_mb, free_mb, used_mb = [int(p.strip()) for p in parts]
        return {
            "total": total_mb * _MIB,
            "free": free_mb * _MIB,
            "used": used_mb * _MIB,
        }
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError) as e:
        logger.debug("VRAM info query failed: %s", e)
        return None


def get_vram_processes() -> list[tuple[int, int, str]]:
    """Query processes currently using GPU VRAM.

    Returns list of (pid, vram_mb, name) tuples, empty list if unavailable.
    """
    if not shutil.which("nvidia-smi"):
        return []
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_gpu_memory,name",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        processes = []
        for line in result.stdout.strip().split("\n"):
            parts = line.split(",")
            if len(parts) != 3:
                continue
            try:
                processes.append((int(parts[0].strip()), int(parts[1].strip()), parts[2].strip()))
            except ValueError:
                continue
        return processes
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug("VRAM process query failed: %s", e)
        return []


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
