"""Docker container lifecycle management.

Replaces docker-compose.yml by using Docker SDK to create and manage containers
with the exact same configuration.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from docker.errors import APIError, ImageNotFound, NotFound
from docker.types import DeviceRequest, Mount

import docker
from ai_shell.defaults import (
    COMFYUI_CONTAINER,
    COMFYUI_DATA_VOLUME,
    COMFYUI_IMAGE,
    KOKORO_CONTAINER,
    KOKORO_IMAGE_CPU,
    KOKORO_IMAGE_GPU,
    LLM_NETWORK,
    N8N_CONTAINER,
    N8N_IMAGE,
    OLLAMA_CONTAINER,
    OLLAMA_CPU_SHARES,
    OLLAMA_DATA_VOLUME,
    OLLAMA_IMAGE,
    OLLAMA_VRAM_BUFFER_BYTES,
    SHM_SIZE,
    VOICE_AGENT_CONTAINER,
    VOICE_AGENT_DATA_VOLUME,
    VOICE_AGENT_IMAGE,
    WEBUI_CONTAINER,
    WEBUI_DATA_VOLUME,
    WEBUI_IMAGE,
    WHISPER_CONTAINER,
    WHISPER_DATA_VOLUME,
    WHISPER_IMAGE_CPU,
    WHISPER_IMAGE_GPU,
    _resolve_env,
    build_dev_environment,
    build_dev_mounts,
    build_n8n_environment,
    build_n8n_mounts,
    dev_container_name,
    project_dev_port,
)
from ai_shell.exceptions import (
    ContainerNotFoundError,
    DockerNotAvailableError,
    GpuRequiredError,
    ImagePullError,
)
from ai_shell.gpu import detect_gpu, get_vram_info

if TYPE_CHECKING:
    from docker.models.containers import Container
    from docker.models.images import Image

    from ai_shell.config import AiShellConfig

logger = logging.getLogger(__name__)


def _exec_docker(args: list[str]) -> NoReturn:
    """Execute a docker CLI command with cross-platform TTY support.

    Uses subprocess.run instead of os.execvp for Windows compatibility.
    On Windows, os.execvp doesn't truly replace the process, causing TTY issues.
    """
    logger.debug("exec: %s", " ".join(args))
    sys.stdout.flush()
    sys.stderr.flush()
    result = subprocess.run(args)
    sys.exit(result.returncode)


def _run_docker(args: list[str]) -> tuple[int, float]:
    """Run a docker CLI command and return (exit_code, elapsed_seconds).

    Unlike _exec_docker, this does NOT call sys.exit().
    """
    logger.debug("run: %s", " ".join(args))
    sys.stdout.flush()
    sys.stderr.flush()
    start = time.monotonic()
    result = subprocess.run(args)
    elapsed = time.monotonic() - start
    return result.returncode, elapsed


def _run_docker_with_typeahead(args: list[str], typeahead: bytes) -> tuple[int, float]:
    """Run docker exec under a PTY, pre-injecting typeahead bytes.

    Used when the user typed during the slow startup phase: those bytes need to
    be replayed into the inner process exactly as if they had been typed once
    the shell attached. Standard subprocess inheritance can't do that because
    we need to inject our own bytes ahead of the live stdin stream.
    """
    import pty
    import select
    import signal
    import termios
    import tty

    logger.debug("run+pty: %s", " ".join(args))
    sys.stdout.flush()
    sys.stderr.flush()

    master_fd, slave_fd = pty.openpty()
    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    original_termios = termios.tcgetattr(stdin_fd)

    # Match the PTY size to the host terminal so curses-based tools render correctly.
    try:
        import fcntl

        size = fcntl.ioctl(stdout_fd, termios.TIOCGWINSZ, b"\x00" * 8)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, size)
    except OSError:
        pass

    def _on_winch(_signum: int, _frame: object) -> None:
        try:
            import fcntl

            size = fcntl.ioctl(stdout_fd, termios.TIOCGWINSZ, b"\x00" * 8)
            fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, size)
        except OSError:
            pass

    previous_winch = signal.signal(signal.SIGWINCH, _on_winch)

    start = time.monotonic()
    proc = subprocess.Popen(
        args,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)

    try:
        tty.setraw(stdin_fd)
        if typeahead:
            os.write(master_fd, typeahead)

        while True:
            if proc.poll() is not None:
                # Drain any final output.
                try:
                    while True:
                        chunk = os.read(master_fd, 4096)
                        if not chunk:
                            break
                        os.write(stdout_fd, chunk)
                except OSError:
                    pass
                break
            try:
                ready, _, _ = select.select([master_fd, stdin_fd], [], [], 0.1)
            except (OSError, ValueError):
                break
            if master_fd in ready:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    chunk = b""
                if not chunk:
                    break
                os.write(stdout_fd, chunk)
            if stdin_fd in ready:
                try:
                    chunk = os.read(stdin_fd, 4096)
                except OSError:
                    chunk = b""
                if chunk:
                    os.write(master_fd, chunk)
    finally:
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, original_termios)
        signal.signal(signal.SIGWINCH, previous_winch)
        try:
            os.close(master_fd)
        except OSError:
            pass
        if proc.poll() is None:
            proc.wait()

    elapsed = time.monotonic() - start
    return proc.returncode, elapsed


class ContainerManager:
    """Manages Docker containers for ai-shell.

    Handles the dev container (per-project) and LLM stack (host-level singletons).
    """

    def __init__(self, config: AiShellConfig) -> None:
        self.config = config
        try:
            self.client = docker.from_env()  # type: ignore[attr-defined]
            self.client.ping()
        except docker.errors.DockerException as e:
            raise DockerNotAvailableError(
                f"Docker is not available. Is the Docker daemon running?\n  Error: {e}"
            ) from e

    # =========================================================================
    # Dev container (per-project)
    # =========================================================================

    def resolve_dev_container(self) -> tuple[str, Container | None]:
        """Resolve the dev container, checking both current and legacy names.

        Returns ``(name, container)`` where *container* is ``None`` when no
        matching container exists.  When no container is found under either
        name, the current hash-based name is returned so callers can use it
        for creation.
        """
        name = dev_container_name(self.config.project_name, self.config.project_dir)
        container = self._get_container(name)
        if container is not None:
            return name, container

        legacy_name = dev_container_name(self.config.project_name)
        legacy_container = self._get_container(legacy_name)
        if legacy_container is not None and self._container_matches_project(
            legacy_container, self.config.project_dir
        ):
            return legacy_name, legacy_container

        return name, None

    def ensure_dev_container(self) -> str:
        """Get or create the dev container for the current project.

        If the container exists but is stopped, it is started.
        If it doesn't exist, it is created with the full configuration.
        If using the ``latest`` tag and a newer image is available, the
        existing container is replaced automatically.

        Returns the container name.
        """
        name, container = self.resolve_dev_container()

        if container is not None:
            if self._recreate_if_image_stale(container, name):
                # Container was removed; fall through to create a new one.
                container = None
            else:
                if container.status != "running":
                    logger.info("Starting existing container: %s", name)
                    container.start()
                return name

        logger.info("Creating dev container: %s", name)
        self._pull_image_if_needed(self.config.full_image)
        self._create_dev_container(name)
        return name

    def _create_dev_container(self, name: str) -> Container:
        """Create the dev container with all docker-compose config."""
        mounts = build_dev_mounts(self.config.project_dir, self.config.project_name)
        environment = build_dev_environment(
            self.config.extra_env,
            self.config.project_dir,
            project_name=self.config.project_name,
            aws_profile=self.config.ai_profile,
            aws_region=self.config.aws_region,
        )

        # MOTD metadata — injected at creation time so the in-container
        # motd.sh script can display version, container identity, and port
        # mappings without querying Docker from inside the container.
        from ai_shell import __version__

        environment["AUGINT_SHELL_VERSION"] = __version__
        environment["AUGINT_CONTAINER_NAME"] = name
        environment["AUGINT_PROJECT_NAME"] = self.config.project_name
        environment["AUGINT_DEV_PORTS"] = ",".join(
            f"{port}:{project_dev_port(self.config.project_dir, port, self.config.project_name)}"
            for port in self.config.dev_ports
        )
        environment["AUGINT_LLM_PORTS"] = ",".join(
            [
                f"ollama:{self.config.ollama_port}",
                f"webui:{self.config.webui_port}",
                f"kokoro:{self.config.kokoro_port}",
                f"whisper:{self.config.whisper_port}",
                f"n8n:{self.config.n8n_port}",
                f"comfyui:{self.config.comfyui_port}",
            ]
        )

        # Add any extra volumes from config
        for vol_spec in self.config.extra_volumes:
            parts = vol_spec.split(":")
            if len(parts) >= 2:
                source, target = parts[0], parts[1]
                read_only = len(parts) > 2 and parts[2] == "ro"
                mounts.append(
                    Mount(
                        target=target,
                        source=source,
                        type="bind",
                        read_only=read_only,
                    )
                )

        container: Container = self.client.containers.run(
            image=self.config.full_image,
            name=name,
            mounts=mounts,
            environment=environment,
            working_dir=f"/root/projects/{self.config.project_name}",
            command="tail -f /dev/null",
            stdin_open=True,
            tty=True,
            shm_size=SHM_SIZE,
            init=True,
            extra_hosts={"host.docker.internal": "host-gateway"},
            ports={
                f"{port}/tcp": (
                    (
                        "0.0.0.0",
                        project_dev_port(self.config.project_dir, port, self.config.project_name),
                    )  # nosec B104
                    if self.config.project_dir
                    else None
                )
                for port in self.config.dev_ports
            },
            detach=True,
        )
        logger.info("Container created: %s", name)

        subprocess.run(
            [
                "docker",
                "exec",
                name,
                "sh",
                "-c",
                "echo 'export PATH=\"/root/.local/bin:/root/.opencode/bin:$PATH\"'"
                " > /etc/profile.d/ai-shell-path.sh",
            ],
            check=False,
            capture_output=True,
        )

        return container

    def exec_interactive(
        self,
        container_name: str,
        command: list[str],
        extra_env: dict[str, str] | None = None,
        workdir: str | None = None,
        typeahead: bytes = b"",
    ) -> NoReturn:
        """Execute an interactive command in a container.

        Uses subprocess.run for cross-platform TTY compatibility.
        Detects whether stdin is a TTY to decide on -i/-t flags.
        If *workdir* is given it is passed as ``-w`` to ``docker exec``.
        When *typeahead* is non-empty and stdin is a TTY, runs the docker exec
        under a PTY so the captured bytes can be replayed into the inner process.
        """
        args = ["docker", "exec"]

        if sys.stdin.isatty():
            args.append("-it")

        if workdir:
            args.extend(["-w", workdir])

        if extra_env:
            for key, value in extra_env.items():
                args.extend(["-e", f"{key}={value}"])

        args.append(container_name)
        args.extend(command)

        if typeahead and sys.platform != "win32" and sys.stdin.isatty():
            exit_code, _ = _run_docker_with_typeahead(args, typeahead)
            sys.exit(exit_code)

        _exec_docker(args)

    def run_interactive(
        self,
        container_name: str,
        command: list[str],
        extra_env: dict[str, str] | None = None,
        workdir: str | None = None,
        typeahead: bytes = b"",
    ) -> tuple[int, float]:
        """Execute an interactive command, returning (exit_code, elapsed_seconds).

        Same as exec_interactive but does not call sys.exit().
        Used for retry logic (e.g., claude -c fallback).
        If *workdir* is given it is passed as ``-w`` to ``docker exec``.
        When *typeahead* is non-empty and stdin is a TTY, runs the docker exec
        under a PTY so the captured bytes can be replayed into the inner process.
        """
        args = ["docker", "exec"]

        if sys.stdin.isatty():
            args.append("-it")

        if workdir:
            args.extend(["-w", workdir])

        if extra_env:
            for key, value in extra_env.items():
                args.extend(["-e", f"{key}={value}"])

        args.append(container_name)
        args.extend(command)

        if typeahead and sys.platform != "win32" and sys.stdin.isatty():
            return _run_docker_with_typeahead(args, typeahead)

        return _run_docker(args)

    def exec_detached(
        self,
        container_name: str,
        command: list[str],
        extra_env: dict[str, str] | None = None,
        workdir: str | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        """Run a command in a container without waiting (docker exec -d)."""
        args = ["docker", "exec", "-d"]
        if workdir:
            args.extend(["-w", workdir])
        if extra_env:
            for key, value in extra_env.items():
                args.extend(["-e", f"{key}={value}"])
        args.append(container_name)
        args.extend(command)
        logger.debug("exec-detached: %s", " ".join(args))
        return subprocess.run(args, check=True)

    # =========================================================================
    # LLM stack (host-level singletons)
    # =========================================================================

    @staticmethod
    def _container_has_gpu(container: Container) -> bool:
        """Return True if *container* was created with a GPU device request."""
        device_requests = container.attrs.get("HostConfig", {}).get("DeviceRequests") or []
        return any(
            "gpu" in (cap for caps in (dr.get("Capabilities") or []) for cap in caps)
            for dr in device_requests
        )

    def _recreate_if_gpu_changed(
        self, container: Container, gpu_available: bool, label: str
    ) -> bool:
        """Remove *container* if its GPU state doesn't match *gpu_available*.

        Returns True if the container was removed (caller must recreate).
        """
        has_gpu = self._container_has_gpu(container)
        if has_gpu == gpu_available:
            return False
        want = "GPU" if gpu_available else "CPU-only"
        had = "GPU" if has_gpu else "CPU-only"
        logger.warning(
            "%s container has %s but system now offers %s — recreating",
            label,
            had,
            want,
        )
        container.remove(force=True)
        return True

    def _recreate_if_image_stale(self, container: Container, name: str) -> bool:
        """Pull the latest image and recreate the container if it is outdated.

        Only acts when the configured tag is ``latest``.  For pinned
        version tags the image is immutable so staleness doesn't apply.

        Returns True if the container was removed (caller must recreate).
        """
        tag = self.config.image_tag
        if tag != "latest":
            return False

        image_ref = self.config.full_image
        try:
            pulled = self.client.images.pull(*image_ref.rsplit(":", 1))
        except APIError:
            logger.debug("Could not pull %s — skipping staleness check", image_ref)
            return False

        self._warn_if_image_below_minimum(pulled)

        container_image_id = container.image.id
        pulled_image_id = pulled.id

        if container_image_id == pulled_image_id:
            return False

        logger.warning(
            "Dev container %s uses an outdated image — recreating with %s",
            name,
            image_ref,
        )
        container.remove(force=True)
        return True

    @staticmethod
    def _warn_if_image_below_minimum(image: Image) -> None:
        """Log a warning if the pulled image version is below the CLI version."""
        from ai_shell import __version__

        labels = image.labels or {}
        image_version_str = labels.get("org.opencontainers.image.version", "")
        if not image_version_str:
            return

        def _parse_version(v: str) -> tuple[int, ...] | None:
            try:
                return tuple(int(x) for x in v.split("."))
            except (ValueError, AttributeError):
                return None

        image_ver = _parse_version(image_version_str)
        cli_ver = _parse_version(__version__)
        if image_ver is None or cli_ver is None:
            return

        if image_ver < cli_ver:
            logger.warning(
                "Container image version %s is older than CLI version %s "
                "— rebuild the image to get the latest tools",
                image_version_str,
                __version__,
            )

    def _ensure_llm_network(self) -> str:
        """Get or create the shared Docker network for the LLM stack."""
        try:
            self.client.networks.get(LLM_NETWORK)
        except NotFound:
            logger.info("Creating LLM network: %s", LLM_NETWORK)
            self.client.networks.create(LLM_NETWORK, driver="bridge")
        return LLM_NETWORK

    def ensure_ollama(self) -> str:
        """Get or create the Ollama container with GPU auto-detection.

        Recreates the container if GPU availability has changed since creation.
        """
        gpu_available = detect_gpu()
        container = self._get_container(OLLAMA_CONTAINER)

        if container is not None:
            if self._recreate_if_gpu_changed(container, gpu_available, "Ollama"):
                pass  # fall through to creation
            else:
                if container.status != "running":
                    logger.info("Starting existing Ollama container")
                    container.start()
                return OLLAMA_CONTAINER

        logger.info("Creating Ollama container")
        self._pull_image_if_needed(OLLAMA_IMAGE)
        network_name = self._ensure_llm_network()
        device_requests = None
        env: dict[str, str] = {
            "OLLAMA_CONTEXT_LENGTH": str(self.config.context_size),
            # Flash attention trims activation memory at no quality cost and
            # is a prerequisite for KV cache quantization.
            "OLLAMA_FLASH_ATTENTION": "1",
            # Quantize the KV cache to 8-bit; near-lossless, halves cache
            # size. Combined with Ollama's dynamic GPU/CPU offload, this
            # buys significant headroom for large models without hard-pinning
            # a num_gpu value in any Modelfile.
            "OLLAMA_KV_CACHE_TYPE": "q8_0",
        }
        if gpu_available:
            device_requests = [DeviceRequest(count=1, capabilities=[["gpu"]])]
            vram = get_vram_info()
            if vram:
                overhead = vram["used"] + OLLAMA_VRAM_BUFFER_BYTES
                env["OLLAMA_GPU_OVERHEAD"] = str(overhead)
                logger.info(
                    "VRAM: %.1f GiB total, %.1f GiB free. Reserving %.1f GiB overhead for Ollama.",
                    vram["total"] / 1024**3,
                    vram["free"] / 1024**3,
                    overhead / 1024**3,
                )
            else:
                logger.info("GPU detected - Ollama will use NVIDIA GPU")
        else:
            logger.warning("No GPU detected - Ollama will run on CPU (slower inference)")

        kwargs: dict = {
            "image": OLLAMA_IMAGE,
            "name": OLLAMA_CONTAINER,
            "ports": {"11434/tcp": ("0.0.0.0", self.config.ollama_port)},  # nosec B104
            "mounts": [
                Mount(
                    target="/root/.ollama",
                    source=OLLAMA_DATA_VOLUME,
                    type="volume",
                )
            ],
            "restart_policy": {"Name": "unless-stopped"},
            "detach": True,
            "network": network_name,
            "cpu_shares": OLLAMA_CPU_SHARES,
        }

        if device_requests:
            kwargs["device_requests"] = device_requests
        if env:
            kwargs["environment"] = env

        self.client.containers.run(**kwargs)
        logger.info("Ollama container created on port %d", self.config.ollama_port)
        return OLLAMA_CONTAINER

    def ensure_webui(
        self,
        voice_enabled: bool = False,
        whisper_enabled: bool = False,
        image_gen_enabled: bool = False,
        env_file: Path | None = None,
    ) -> str:
        """Get or create the Open WebUI container.

        When *voice_enabled* is True, pre-wires Kokoro TTS as the speech
        backend.  When *whisper_enabled* is True, pre-wires Speaches STT
        as the transcription backend.  When *image_gen_enabled* is True,
        pre-wires ComfyUI as the image-generation backend.  API keys from
        *env_file* (or host environment) are passed through so WebUI can
        offer external LLM providers alongside Ollama.
        """
        container = self._get_container(WEBUI_CONTAINER)

        if container is not None:
            if container.status != "running":
                logger.info("Starting existing WebUI container")
                container.start()
            return WEBUI_CONTAINER

        logger.info("Creating Open WebUI container")
        self._pull_image_if_needed(WEBUI_IMAGE)
        network_name = self._ensure_llm_network()

        from dotenv import dotenv_values

        from ai_shell.defaults import _resolve_env

        dotenv: dict[str, str | None] = {}
        if env_file is not None:
            dotenv = dotenv_values(env_file)

        environment: dict[str, str] = {
            "OLLAMA_BASE_URL": f"http://{OLLAMA_CONTAINER}:11434",
            "WEBUI_AUTH": "false",
            # DEFAULT_MODELS is a PersistentConfig: env seeds the DB on first
            # boot and UI edits win after that.  Point new chats at the
            # primary chat slot; users can pick the secondary (uncensored)
            # from the model dropdown.
            "DEFAULT_MODELS": self.config.primary_chat_model,
        }
        if voice_enabled:
            environment.update(
                {
                    "AUDIO_TTS_ENGINE": "openai",
                    "AUDIO_TTS_OPENAI_API_BASE_URL": f"http://{KOKORO_CONTAINER}:8880/v1",
                    "AUDIO_TTS_OPENAI_API_KEY": "dummy",
                    "AUDIO_TTS_MODEL": "kokoro",
                    "AUDIO_TTS_VOICE": self.config.kokoro_voice,
                }
            )
        if whisper_enabled:
            environment.update(
                {
                    "AUDIO_STT_ENGINE": "openai",
                    "AUDIO_STT_OPENAI_API_BASE_URL": f"http://{WHISPER_CONTAINER}:8000/v1",
                    "AUDIO_STT_OPENAI_API_KEY": "dummy",
                    "AUDIO_STT_MODEL": self.config.whisper_model,
                }
            )
        if image_gen_enabled:
            # ENABLE_IMAGE_GENERATION + IMAGE_GENERATION_ENGINE=comfyui are
            # PersistentConfig keys; they seed the DB on first boot. Users can
            # later override the default workflow or model via Settings > Images.
            environment.update(
                {
                    "ENABLE_IMAGE_GENERATION": "true",
                    "IMAGE_GENERATION_ENGINE": "comfyui",
                    "COMFYUI_BASE_URL": f"http://{COMFYUI_CONTAINER}:8188",
                    "IMAGE_SIZE": "1024x1024",
                    "IMAGE_STEPS": "25",
                }
            )

        # External LLM providers — pass through API keys when available.
        openai_urls: list[str] = []
        openai_keys: list[str] = []

        openai_key = _resolve_env(dotenv, "OPENAI_API_KEY")
        if openai_key:
            openai_urls.append("https://api.openai.com/v1")
            openai_keys.append(openai_key)

        gh_token = _resolve_env(dotenv, "GH_TOKEN")
        if gh_token:
            openai_urls.append("https://models.inference.ai.azure.com/v1")
            openai_keys.append(gh_token)

        if openai_urls:
            environment["OPENAI_API_BASE_URLS"] = ";".join(openai_urls)
            environment["OPENAI_API_KEYS"] = ";".join(openai_keys)

        anthropic_key = _resolve_env(dotenv, "ANTHROPIC_API_KEY")
        if anthropic_key:
            environment["ANTHROPIC_API_KEY"] = anthropic_key

        self.client.containers.run(
            image=WEBUI_IMAGE,
            name=WEBUI_CONTAINER,
            ports={"8080/tcp": ("0.0.0.0", self.config.webui_port)},  # nosec B104
            environment=environment,
            mounts=[
                Mount(
                    target="/app/backend/data",
                    source=WEBUI_DATA_VOLUME,
                    type="volume",
                )
            ],
            restart_policy={"Name": "unless-stopped"},
            detach=True,
            network=network_name,
        )

        logger.info("Open WebUI container created on port %d", self.config.webui_port)
        return WEBUI_CONTAINER

    def ensure_kokoro(self) -> str:
        """Get or create the Kokoro-FastAPI (local TTS) container.

        Exposes an OpenAI-compatible ``/v1/audio/speech`` endpoint on the
        configured port. GPU image is used when NVIDIA is detected;
        otherwise the CPU image. Recreates if GPU availability has changed.
        """
        gpu_available = detect_gpu()
        container = self._get_container(KOKORO_CONTAINER)
        if container is not None:
            if self._recreate_if_gpu_changed(container, gpu_available, "Kokoro"):
                pass  # fall through to creation
            else:
                if container.status != "running":
                    logger.info("Starting existing Kokoro container")
                    container.start()
                return KOKORO_CONTAINER
        image = KOKORO_IMAGE_GPU if gpu_available else KOKORO_IMAGE_CPU
        logger.info("Creating Kokoro container (%s)", "GPU" if gpu_available else "CPU")
        self._pull_image_if_needed(image)
        network_name = self._ensure_llm_network()

        kwargs: dict = {
            "image": image,
            "name": KOKORO_CONTAINER,
            "ports": {"8880/tcp": ("0.0.0.0", self.config.kokoro_port)},  # nosec B104
            "restart_policy": {"Name": "unless-stopped"},
            "detach": True,
            "network": network_name,
        }
        if gpu_available:
            kwargs["device_requests"] = [DeviceRequest(count=1, capabilities=[["gpu"]])]

        self.client.containers.run(**kwargs)
        logger.info("Kokoro container created on port %d", self.config.kokoro_port)
        return KOKORO_CONTAINER

    def ensure_whisper(self) -> str:
        """Get or create the Speaches (local STT) container.

        Exposes an OpenAI-compatible ``/v1/audio/transcriptions`` endpoint on
        the configured port. GPU image is used when NVIDIA is detected;
        otherwise the CPU image. Recreates if GPU availability has changed.
        The Hugging Face model cache persists in a named volume (Speaches runs
        as ``ubuntu`` UID 1000 — a named volume inherits the correct ownership;
        bind-mounting a host dir here would require an explicit chown).
        """
        gpu_available = detect_gpu()
        container = self._get_container(WHISPER_CONTAINER)
        if container is not None:
            if self._recreate_if_gpu_changed(container, gpu_available, "Whisper"):
                pass  # fall through to creation
            else:
                if container.status != "running":
                    logger.info("Starting existing Whisper container")
                    container.start()
                return WHISPER_CONTAINER
        image = WHISPER_IMAGE_GPU if gpu_available else WHISPER_IMAGE_CPU
        logger.info("Creating Whisper container (%s)", "GPU" if gpu_available else "CPU")
        self._pull_image_if_needed(image)
        network_name = self._ensure_llm_network()

        # PRELOAD_MODELS uses pydantic-settings JSON array syntax, not CSV.
        # json.dumps guarantees correct escaping for any model id.
        environment = {
            "WHISPER__INFERENCE_DEVICE": "auto",
            "PRELOAD_MODELS": json.dumps([self.config.whisper_model]),
        }

        kwargs: dict = {
            "image": image,
            "name": WHISPER_CONTAINER,
            "ports": {"8000/tcp": ("0.0.0.0", self.config.whisper_port)},  # nosec B104
            "environment": environment,
            "mounts": [
                Mount(
                    target="/home/ubuntu/.cache/huggingface/hub",
                    source=WHISPER_DATA_VOLUME,
                    type="volume",
                )
            ],
            "restart_policy": {"Name": "unless-stopped"},
            "detach": True,
            "network": network_name,
        }
        if gpu_available:
            kwargs["device_requests"] = [DeviceRequest(count=1, capabilities=[["gpu"]])]

        self.client.containers.run(**kwargs)
        logger.info("Whisper container created on port %d", self.config.whisper_port)
        return WHISPER_CONTAINER

    def ensure_voice_agent(self) -> str:
        """Get or create the voice-agent container.

        The image is **built locally** from ``docker/voice-agent/`` on first
        call because Phase 2 doesn't publish it. Later phases may switch to
        a pulled tag. Phase 2 scope: no filesystem / auth / provider-key
        mounts — those land in Phases 3-4. A named volume is mounted at
        ``/data`` so the Phase 5 sqlite file will survive container
        recreations from the start. Service-discovery URLs for sibling
        stacks (ComfyUI, etc.) are exported so later phases can dispatch
        tool calls without re-reading config.
        """
        container = self._get_container(VOICE_AGENT_CONTAINER)
        if container is not None:
            if container.status != "running":
                logger.info("Starting existing voice-agent container")
                container.start()
            return VOICE_AGENT_CONTAINER

        logger.info("Creating voice-agent container")
        self._build_image_if_needed(VOICE_AGENT_IMAGE, self._voice_agent_build_context())
        network_name = self._ensure_llm_network()

        kwargs: dict = {
            "image": VOICE_AGENT_IMAGE,
            "name": VOICE_AGENT_CONTAINER,
            "ports": {"8000/tcp": ("0.0.0.0", self.config.voice_agent.port)},  # nosec B104
            "environment": {
                "COMFYUI_BASE_URL": f"http://{COMFYUI_CONTAINER}:8188",
            },
            "mounts": [
                Mount(
                    target="/data",
                    source=VOICE_AGENT_DATA_VOLUME,
                    type="volume",
                )
            ],
            "restart_policy": {"Name": "unless-stopped"},
            "detach": True,
            "network": network_name,
        }

        self.client.containers.run(**kwargs)
        logger.info("voice-agent container created on port %d", self.config.voice_agent.port)
        return VOICE_AGENT_CONTAINER

    @staticmethod
    def _voice_agent_build_context() -> str:
        """Return the path to the voice-agent Dockerfile build context."""
        # Package layout: src/ai_shell/container.py — the Dockerfile lives in
        # <repo root>/docker/voice-agent. When installed as a wheel the user
        # is expected to have the source checked out; voice-agent is
        # experimental and locally built for now.
        here = Path(__file__).resolve()
        return str(here.parents[2] / "docker" / "voice-agent")

    def ensure_comfyui(self, env_file: Path | None = None) -> str:
        """Get or create the ComfyUI image-generation container.

        GPU-required (the ai-dock image has no CPU variant). On first
        boot, ai-dock runs the bind-mounted provisioning script which
        downloads SDXL unconditionally and FLUX.1-dev when ``HF_TOKEN``
        is present in *env_file* or the host environment. Model files
        persist in a named volume so subsequent containers start without
        re-downloading ~25 GB. Recreates the container when GPU
        availability toggles, matching the Kokoro/Whisper pattern.
        """
        from dotenv import dotenv_values

        gpu_available = detect_gpu()
        container = self._get_container(COMFYUI_CONTAINER)
        if container is not None:
            if self._recreate_if_gpu_changed(container, gpu_available, "ComfyUI"):
                pass  # fall through to creation
            else:
                if container.status != "running":
                    logger.info("Starting existing ComfyUI container")
                    container.start()
                return COMFYUI_CONTAINER

        if not gpu_available:
            raise GpuRequiredError("ComfyUI")

        logger.info("Creating ComfyUI container")
        self._pull_image_if_needed(COMFYUI_IMAGE)
        network_name = self._ensure_llm_network()

        dotenv: dict[str, str | None] = {}
        if env_file is not None:
            dotenv = dotenv_values(env_file)

        hf_token = _resolve_env(dotenv, "HF_TOKEN") or _resolve_env(
            dotenv, "HUGGING_FACE_HUB_TOKEN"
        )

        environment: dict[str, str] = {
            # --lowvram keeps FLUX's 12B weights offloading through CPU RAM so
            # Ollama can keep a chat model resident on the same GPU. --listen
            # binds on 0.0.0.0 so other containers on the LLM network can reach
            # the API.
            "CLI_ARGS": "--lowvram --listen 0.0.0.0",
            # ai-dock runs PROVISIONING_SCRIPT once per workspace. We bind-mount
            # our own script at a known path rather than hosting one remotely.
            "PROVISIONING_SCRIPT": "/opt/augint/provision.sh",
            # Local-dev deployment: disable ai-dock's Caddy basic-auth layer so
            # the port-8188 service is reachable without redirect-to-/login.
            # Matches WEBUI_AUTH=false on Open WebUI.
            "WEB_ENABLE_AUTH": "false",
            "CF_QUICK_TUNNELS": "false",
        }
        if hf_token:
            # ai-dock's provisioner reads HF_TOKEN; upstream HF libs read
            # HUGGING_FACE_HUB_TOKEN. Set both to avoid edge cases.
            environment["HF_TOKEN"] = hf_token
            environment["HUGGING_FACE_HUB_TOKEN"] = hf_token

        provision_path = Path(__file__).parent / "assets" / "comfyui" / "provision.sh"
        mounts: list[Mount] = [
            Mount(
                target="/opt/ComfyUI/models",
                source=COMFYUI_DATA_VOLUME,
                type="volume",
            )
        ]
        if provision_path.is_file():
            mounts.append(
                Mount(
                    target="/opt/augint/provision.sh",
                    source=str(provision_path),
                    type="bind",
                    read_only=True,
                )
            )

        kwargs: dict = {
            "image": COMFYUI_IMAGE,
            "name": COMFYUI_CONTAINER,
            "ports": {"8188/tcp": ("0.0.0.0", self.config.comfyui_port)},  # nosec B104
            "environment": environment,
            "mounts": mounts,
            "restart_policy": {"Name": "unless-stopped"},
            "detach": True,
            "network": network_name,
            "device_requests": [DeviceRequest(count=1, capabilities=[["gpu"]])],
        }

        self.client.containers.run(**kwargs)
        logger.info("ComfyUI container created on port %d", self.config.comfyui_port)
        return COMFYUI_CONTAINER

    def ensure_n8n(self, env_file: Path | None = None) -> str:
        """Get or create the n8n workflow automation container.

        Pre-wires service discovery URLs (Ollama, Kokoro, Speaches,
        Voice Agent, WebUI) and passes through API keys (OpenAI,
        Anthropic, GitHub, AWS) from *env_file* or the host environment.
        Credential directories (``~/.aws``, ``~/.config/gh``) are mounted
        read-only so n8n's AWS and GitHub nodes authenticate automatically.
        """
        container = self._get_container(N8N_CONTAINER)

        if container is not None:
            if container.status != "running":
                logger.info("Starting existing n8n container")
                container.start()
            return N8N_CONTAINER

        logger.info("Creating n8n container")
        self._pull_image_if_needed(N8N_IMAGE)
        network_name = self._ensure_llm_network()

        environment = build_n8n_environment(
            env_file=env_file,
            aws_profile=self.config.ai_profile,
            aws_region=self.config.aws_region,
        )

        workflow_dir = Path(__file__).parent / "templates" / "n8n" / "workflows"
        mounts = build_n8n_mounts(
            workflow_dir=workflow_dir if workflow_dir.is_dir() else None,
        )

        created = True
        self.client.containers.run(
            image=N8N_IMAGE,
            name=N8N_CONTAINER,
            ports={"5678/tcp": ("0.0.0.0", self.config.n8n_port)},  # nosec B104
            environment=environment,
            mounts=mounts,
            restart_policy={"Name": "unless-stopped"},
            detach=True,
            network=network_name,
        )

        logger.info("n8n container created on port %d", self.config.n8n_port)

        if created and workflow_dir.is_dir():
            self._seed_n8n_workflows()

        return N8N_CONTAINER

    def _seed_n8n_workflows(self) -> None:
        """Import starter workflow templates into a freshly-created n8n.

        Workflows are mounted at ``/workflows`` inside the container.  We
        wait for n8n to be ready, then use ``n8n import:workflow`` to load
        each JSON file.  Failures are logged but never fatal.
        """
        container = self._get_container(N8N_CONTAINER)
        if container is None:
            return

        # Wait for n8n to become ready (max ~30 s).
        for _i in range(15):
            try:
                exit_code, _ = container.exec_run("curl -sf http://localhost:5678/healthz")
                if exit_code == 0:
                    break
            except Exception:
                pass
            time.sleep(2)
        else:
            logger.warning("n8n did not become healthy in 30 s; skipping workflow seed")
            return

        # Check for the seed marker to avoid duplicate imports.
        exit_code, _ = container.exec_run("test -f /home/node/.n8n/.workflows-seeded")
        if exit_code == 0:
            logger.debug("n8n workflows already seeded; skipping")
            return

        # Import each workflow template.
        exit_code, output = container.exec_run("ls /workflows/")
        if exit_code != 0:
            logger.debug("No /workflows directory in n8n container")
            return

        for line in output.decode().strip().splitlines():
            fname = line.strip()
            if not fname.endswith(".json"):
                continue
            logger.info("Importing n8n workflow: %s", fname)
            exit_code, out = container.exec_run(f"n8n import:workflow --input=/workflows/{fname}")
            if exit_code != 0:
                logger.warning("Failed to import %s: %s", fname, out.decode())

        # Write seed marker so we don't re-import on next restart.
        container.exec_run("touch /home/node/.n8n/.workflows-seeded")

    def exec_in_ollama(self, command: list[str]) -> str:
        """Run a command in the Ollama container and return stdout.

        Used for: ollama pull, ollama list, ollama create.
        """
        container = self._get_container(OLLAMA_CONTAINER)
        if container is None or container.status != "running":
            raise ContainerNotFoundError(OLLAMA_CONTAINER)

        exit_code, output = container.exec_run(
            cmd=command,
            stdout=True,
            stderr=True,
        )
        decoded: str = output.decode("utf-8", errors="replace")
        if exit_code != 0:
            logger.error("Command failed in ollama: %s\n%s", " ".join(command), decoded)
        return decoded

    # =========================================================================
    # Container lifecycle
    # =========================================================================

    def stop_container(self, name: str) -> None:
        """Stop a container by name."""
        container = self._get_container(name)
        if container is None:
            raise ContainerNotFoundError(name)
        if container.status == "running":
            container.stop()
            logger.info("Stopped container: %s", name)

    def remove_container(self, name: str) -> None:
        """Remove a container by name, stopping it first if running."""
        container = self._get_container(name)
        if container is None:
            raise ContainerNotFoundError(name)
        if container.status == "running":
            container.stop()
            logger.info("Stopped container: %s", name)
        container.remove()
        logger.info("Removed container: %s", name)

    def remove_volume(self, name: str) -> bool:
        """Remove a named Docker volume.

        Returns True if a volume was removed, False if it did not exist.
        """
        try:
            volume = self.client.volumes.get(name)
        except NotFound:
            return False
        volume.remove()
        logger.info("Removed volume: %s", name)
        return True

    def container_ports(self, name: str) -> dict[str, str] | None:
        """Get the port mappings for a container.

        Returns a dict mapping container ports (e.g. '3000/tcp') to host
        addresses (e.g. '0.0.0.0:49152'), or None if the container doesn't exist.
        """
        container = self._get_container(name)
        if container is None:
            return None
        container.reload()
        ports_data = container.attrs.get("NetworkSettings", {}).get("Ports") or {}
        result: dict[str, str] = {}
        for container_port, bindings in sorted(ports_data.items()):
            if bindings:
                binding = bindings[0]
                result[container_port] = f"{binding['HostIp']}:{binding['HostPort']}"
        return result

    def container_status(self, name: str) -> str | None:
        """Get the status of a container, or None if it doesn't exist."""
        container = self._get_container(name)
        if container is None:
            return None
        return container.status  # type: ignore[no-any-return]

    def container_logs(self, name: str, follow: bool = False, tail: int = 100) -> None:
        """Print container logs. If follow=True, streams via docker CLI."""
        if follow:
            # Use docker CLI for streaming
            args = ["docker", "logs", "-f", name]
            _exec_docker(args)
        else:
            container = self._get_container(name)
            if container is None:
                raise ContainerNotFoundError(name)
            logs = container.logs(tail=tail).decode("utf-8", errors="replace")
            print(logs)

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _get_container(self, name: str) -> Container | None:
        """Get a container by name, or None if it doesn't exist."""
        try:
            return self.client.containers.get(name)
        except NotFound:
            return None

    def _container_matches_project(self, container: Container, project_dir: Path) -> bool:
        """Check whether a container's project mount matches *project_dir*."""
        resolved_project_dir = str(project_dir.resolve())
        mounts = container.attrs.get("Mounts", [])
        for mount in mounts:
            if mount.get("Source") == resolved_project_dir:
                return True
        return False

    # AUTO-UPDATE: Pre-launch tool freshness check
    def ensure_tool_fresh(self, container_name: str, tool_name: str) -> None:
        """Check if a tool is stale and update it before launch.

        Runs ``update-tools.sh --check <tool>`` inside the container.
        If stale (exit code 1), runs ``--tool <tool>`` in the foreground
        (blocking) which also kicks off background updates for other tools.

        Silently does nothing if ``update-tools.sh`` is not present in the
        container (backward compatibility with older images), or if
        ``config.skip_updates`` is True (``--skip-updates`` flag).
        """
        if self.config.skip_updates:
            logger.debug("Skipping tool freshness check (--skip-updates)")
            return

        update_script = "/usr/local/bin/update-tools.sh"

        # Check if update script exists in the container
        check_exists = subprocess.run(
            ["docker", "exec", container_name, "test", "-x", update_script],
            capture_output=True,
        )
        if check_exists.returncode != 0:
            logger.debug(
                "update-tools.sh not found in %s, skipping freshness check",
                container_name,
            )
            return

        # Check freshness
        check_result = subprocess.run(
            ["docker", "exec", container_name, update_script, "--check", tool_name],
            capture_output=True,
        )
        if check_result.returncode == 0:
            logger.debug("Tool %s is fresh, skipping update", tool_name)
            return

        # Tool is stale — update it in foreground (--tool also backgrounds the rest)
        from rich.console import Console

        console = Console(stderr=True)
        with console.status(f"[bold]Updating {tool_name}...[/bold]", spinner="dots"):
            update_result = subprocess.run(
                ["docker", "exec", container_name, update_script, "--tool", tool_name],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )
        if update_result.returncode == 0:
            console.print(f"[green]Updated {tool_name}[/green]")
        else:
            console.print(f"[yellow]Update for {tool_name} had issues, continuing anyway[/yellow]")
            logger.debug("Update stderr: %s", update_result.stderr)

    def _build_image_if_needed(self, image: str, context_path: str) -> None:
        """Build a Docker image locally if it isn't already present.

        Used for images we don't pull from a registry (experimental
        components shipped as a Dockerfile in this repo). The local tag
        is cached between runs; a rebuild requires removing the image
        first (``docker rmi <tag>``).
        """
        try:
            self.client.images.get(image)
            logger.debug("Image already built: %s", image)
            return
        except ImageNotFound:
            pass

        logger.info("Building image: %s from %s ...", image, context_path)
        try:
            self.client.images.build(path=context_path, tag=image, rm=True)
            logger.info("Image built: %s", image)
        except APIError as e:
            raise ImagePullError(image, f"build failed: {e}") from e

    def _pull_image_if_needed(self, image: str) -> None:
        """Pull a Docker image if not available locally.

        For the ``latest`` tag, always pull to ensure the freshest digest
        since the local cache may be stale.  If the pull fails but a
        cached copy exists, falls back to the cached version with a
        warning.
        """
        tag = image.rsplit(":", 1)[-1] if ":" in image else "latest"

        # AUTO-UPDATE: Always pull 'latest' to get fresh images
        if tag != "latest":
            try:
                self.client.images.get(image)
                logger.debug("Image already available: %s", image)
                return
            except ImageNotFound:
                pass

        logger.info("Pulling image: %s (this may take a while)...", image)
        try:
            pulled = self.client.images.pull(*image.rsplit(":", 1))
            self._warn_if_image_below_minimum(pulled)
            logger.info("Image pulled: %s", image)
        except APIError as e:
            if tag == "latest":
                try:
                    self.client.images.get(image)
                    logger.warning("Failed to pull latest image, using cached version: %s", e)
                    return
                except ImageNotFound:
                    pass
            raise ImagePullError(image, str(e)) from e
