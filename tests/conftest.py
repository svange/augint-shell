"""Shared test fixtures for ai-shell."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ai_shell.config import AiShellConfig


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    return project_dir


@pytest.fixture
def config(tmp_project: Path) -> AiShellConfig:
    """Create a default config pointing at the temp project."""
    return AiShellConfig(
        project_name="test-project",
        project_dir=tmp_project,
    )


@pytest.fixture
def mock_docker_client():
    """Create a mocked Docker client."""
    client = MagicMock()
    client.ping.return_value = True
    client.containers = MagicMock()
    client.images = MagicMock()
    return client


@pytest.fixture
def mock_container_manager(config, mock_docker_client):
    """Create a ContainerManager with a mocked Docker client."""
    with patch("ai_shell.container.docker") as mock_docker:
        mock_docker.from_env.return_value = mock_docker_client
        mock_docker.errors = MagicMock()
        mock_docker.errors.DockerException = Exception

        from ai_shell.container import ContainerManager

        manager = ContainerManager(config)
        yield manager
