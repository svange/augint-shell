"""Docker container lifecycle management.

Replaces docker-compose.yml by using Docker SDK to create and manage containers
with the exact same configuration.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from typing import TYPE_CHECKING, NoReturn

from docker.errors import APIError, ImageNotFound, NotFound
from docker.types import DeviceRequest, Mount

import docker
from ai_shell.defaults import (
    KOKORO_CONTAINER,
    KOKORO_IMAGE_CPU,
    KOKORO_IMAGE_GPU,
    LLM_NETWORK,
    N8N_CONTAINER,
    N8N_DATA_VOLUME,
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
    build_dev_environment,
    build_dev_mounts,
    dev_container_name,
    project_dev_port,
)
from ai_shell.exceptions import (
    ContainerNotFoundError,
    DockerNotAvailableError,
    ImagePullError,
)
from ai_shell.gpu import detect_gpu, get_vram_info

if TYPE_CHECKING:
    from pathlib import Path

    from docker.models.containers import Container

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

        Returns the container name.
        """
        name, container = self.resolve_dev_container()

        if container is not None:
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
        return container

    def exec_interactive(
        self,
        container_name: str,
        command: list[str],
        extra_env: dict[str, str] | None = None,
        workdir: str | None = None,
    ) -> NoReturn:
        """Execute an interactive command in a container.

        Uses subprocess.run for cross-platform TTY compatibility.
        Detects whether stdin is a TTY to decide on -i/-t flags.
        If *workdir* is given it is passed as ``-w`` to ``docker exec``.
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

        _exec_docker(args)

    def run_interactive(
        self,
        container_name: str,
        command: list[str],
        extra_env: dict[str, str] | None = None,
        workdir: str | None = None,
    ) -> tuple[int, float]:
        """Execute an interactive command, returning (exit_code, elapsed_seconds).

        Same as exec_interactive but does not call sys.exit().
        Used for retry logic (e.g., claude -c fallback).
        If *workdir* is given it is passed as ``-w`` to ``docker exec``.
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

        return _run_docker(args)

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

    def ensure_webui(self, voice_enabled: bool = False) -> str:
        """Get or create the Open WebUI container.

        When *voice_enabled* is True, pre-wires the container to use the
        Kokoro TTS container as its OpenAI-compatible speech backend so
        the user doesn't need to configure it in the UI.
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

        environment = {
            "OLLAMA_BASE_URL": f"http://{OLLAMA_CONTAINER}:11434",
            "WEBUI_AUTH": "false",
            # DEFAULT_MODELS is a PersistentConfig: env seeds the DB on first
            # boot and UI edits win after that. Point new chats at the
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
        recreations from the start.
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
        from pathlib import Path as _Path

        # Package layout: src/ai_shell/container.py — the Dockerfile lives in
        # <repo root>/docker/voice-agent. When installed as a wheel the user
        # is expected to have the source checked out; voice-agent is
        # experimental and locally built for now.
        here = _Path(__file__).resolve()
        return str(here.parents[2] / "docker" / "voice-agent")

    def ensure_n8n(self) -> str:
        """Get or create the n8n workflow automation container.

        Standalone service; does not integrate with Ollama or Kokoro. Data
        (workflows, credentials, settings) is persisted to a named volume.
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

        environment = {
            # Disable secure-cookie enforcement so the UI works over plain
            # http://localhost without a reverse proxy.
            "N8N_SECURE_COOKIE": "false",
        }

        self.client.containers.run(
            image=N8N_IMAGE,
            name=N8N_CONTAINER,
            ports={"5678/tcp": ("0.0.0.0", self.config.n8n_port)},  # nosec B104
            environment=environment,
            mounts=[
                Mount(
                    target="/home/node/.n8n",
                    source=N8N_DATA_VOLUME,
                    type="volume",
                )
            ],
            restart_policy={"Name": "unless-stopped"},
            detach=True,
            network=network_name,
        )

        logger.info("n8n container created on port %d", self.config.n8n_port)
        return N8N_CONTAINER

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
            self.client.images.pull(*image.rsplit(":", 1))
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
