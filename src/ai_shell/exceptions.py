"""Custom exceptions for ai-shell."""


class AiShellError(Exception):
    """Base exception for ai-shell."""


class DockerNotAvailableError(AiShellError):
    """Docker daemon is not running or not installed."""


class ImagePullError(AiShellError):
    """Failed to pull Docker image."""

    def __init__(self, image: str, reason: str) -> None:
        self.image = image
        self.reason = reason
        super().__init__(f"Failed to pull {image}: {reason}")


class ContainerNotFoundError(AiShellError):
    """Container does not exist."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Container '{name}' not found")


class ConfigError(AiShellError):
    """Invalid configuration."""
