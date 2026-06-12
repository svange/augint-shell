"""Shared fixtures for unit tests."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def isolate_home(tmp_path):
    """Prevent tests from reading real ~/.augint/ config files."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    with patch("pathlib.Path.home", return_value=fake_home):
        yield fake_home


@pytest.fixture(autouse=True)
def no_docker_tcp_probe():
    """Prevent container-creation tests from probing localhost:2375.

    docker_tcp_fallback_host opens a real socket when no Docker socket file
    exists; tests must never depend on the machine's network state. Tests for
    the fallback itself override this with their own patch.
    """
    with patch("ai_shell.container.docker_tcp_fallback_host", return_value=None):
        yield


@pytest.fixture(autouse=True)
def no_host_port_probe():
    """Make the host port availability probe a no-op in tests.

    _host_port_available test-binds real sockets; port assignments in tests
    must stay deterministic regardless of what's listening on the machine.
    """
    with patch("ai_shell.container._host_port_available", return_value=True):
        yield
