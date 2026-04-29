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
