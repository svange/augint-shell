"""Docker container lifecycle management.

Replaces docker-compose.yml by using Docker SDK to create and manage containers
with the exact same configuration.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import TYPE_CHECKING, NoReturn

from docker.errors import APIError, ImageNotFound, NotFound
from docker.types import DeviceRequest, Mount

import docker
from ai_shell.defaults import (
    OLLAMA_CONTAINER,
    OLLAMA_DATA_VOLUME,
    OLLAMA_IMAGE,
    SHM_SIZE,
    WEBUI_CONTAINER,
    WEBUI_DATA_VOLUME,
    WEBUI_IMAGE,
    build_dev_environment,
    build_dev_mounts,
    dev_container_name,
)
from ai_shell.exceptions import (
    ContainerNotFoundError,
    DockerNotAvailableError,
    ImagePullError,
)
from ai_shell.gpu import detect_gpu

if TYPE_CHECKING:
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

    def ensure_dev_container(self) -> str:
        """Get or create the dev container for the current project.

        If the container exists but is stopped, it is started.
        If it doesn't exist, it is created with the full configuration.

        Returns the container name.
        """
        name = dev_container_name(self.config.project_name)
        container = self._get_container(name)

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
        environment = build_dev_environment(self.config.extra_env)

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
            ports={"5678/tcp": None, "8000/tcp": None},
            detach=True,
        )
        logger.info("Container created: %s", name)
        return container

    def exec_interactive(
        self,
        container_name: str,
        command: list[str],
        extra_env: dict[str, str] | None = None,
    ) -> NoReturn:
        """Execute an interactive command in a container.

        Uses subprocess.run for cross-platform TTY compatibility.
        Detects whether stdin is a TTY to decide on -i/-t flags.
        """
        args = ["docker", "exec"]

        if sys.stdin.isatty():
            args.append("-it")

        if extra_env:
            for key, value in extra_env.items():
                args.extend(["-e", f"{key}={value}"])

        args.append(container_name)
        args.extend(command)

        _exec_docker(args)

    # =========================================================================
    # LLM stack (host-level singletons)
    # =========================================================================

    def ensure_ollama(self) -> str:
        """Get or create the Ollama container with GPU auto-detection.

        Returns the container name.
        """
        container = self._get_container(OLLAMA_CONTAINER)

        if container is not None:
            if container.status != "running":
                logger.info("Starting existing Ollama container")
                container.start()
            return OLLAMA_CONTAINER

        logger.info("Creating Ollama container")
        self._pull_image_if_needed(OLLAMA_IMAGE)

        # GPU auto-detection
        gpu_available = detect_gpu()
        device_requests = None
        if gpu_available:
            device_requests = [DeviceRequest(count=1, capabilities=[["gpu"]])]
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
        }

        if device_requests:
            kwargs["device_requests"] = device_requests

        self.client.containers.run(**kwargs)
        logger.info("Ollama container created on port %d", self.config.ollama_port)
        return OLLAMA_CONTAINER

    def ensure_webui(self) -> str:
        """Get or create the Open WebUI container.

        Returns the container name.
        """
        container = self._get_container(WEBUI_CONTAINER)

        if container is not None:
            if container.status != "running":
                logger.info("Starting existing WebUI container")
                container.start()
            return WEBUI_CONTAINER

        logger.info("Creating Open WebUI container")
        self._pull_image_if_needed(WEBUI_IMAGE)

        self.client.containers.run(
            image=WEBUI_IMAGE,
            name=WEBUI_CONTAINER,
            ports={"8080/tcp": ("0.0.0.0", self.config.webui_port)},  # nosec B104
            environment={
                "OLLAMA_BASE_URL": f"http://{OLLAMA_CONTAINER}:11434",
                "WEBUI_AUTH": "false",
            },
            mounts=[
                Mount(
                    target="/app/backend/data",
                    source=WEBUI_DATA_VOLUME,
                    type="volume",
                )
            ],
            restart_policy={"Name": "unless-stopped"},
            detach=True,
            # Link to ollama via Docker network
            network_mode=f"container:{OLLAMA_CONTAINER}",
        )

        logger.info("Open WebUI container created on port %d", self.config.webui_port)
        return WEBUI_CONTAINER

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

    def remove_container(self, name: str, force: bool = False) -> None:
        """Remove a container by name."""
        container = self._get_container(name)
        if container is None:
            raise ContainerNotFoundError(name)
        container.remove(force=force)
        logger.info("Removed container: %s", name)

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

    def _pull_image_if_needed(self, image: str) -> None:
        """Pull a Docker image if not available locally."""
        try:
            self.client.images.get(image)
            logger.debug("Image already available: %s", image)
        except ImageNotFound:
            logger.info("Pulling image: %s (this may take a while)...", image)
            try:
                self.client.images.pull(*image.rsplit(":", 1))
                logger.info("Image pulled: %s", image)
            except APIError as e:
                raise ImagePullError(image, str(e)) from e
