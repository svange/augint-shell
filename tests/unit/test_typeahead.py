"""Tests for ai_shell.typeahead capture context manager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ai_shell.typeahead import TypeaheadBuffer, capture_typeahead


class TestTypeaheadBuffer:
    def test_bytes_default_empty(self) -> None:
        buf = TypeaheadBuffer()
        assert buf.bytes() == b""

    def test_append_accumulates(self) -> None:
        buf = TypeaheadBuffer()
        buf.append(b"hel")
        buf.append(b"lo")
        assert buf.bytes() == b"hello"

    def test_append_empty_is_noop(self) -> None:
        buf = TypeaheadBuffer()
        buf.append(b"")
        buf.append(b"x")
        assert buf.bytes() == b"x"


class TestCaptureTypeahead:
    def test_noop_when_stdin_not_a_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = False
        monkeypatch.setattr("ai_shell.typeahead.sys.stdin", fake_stdin)

        with capture_typeahead() as buf:
            assert buf.bytes() == b""
        assert buf.bytes() == b""

    def test_noop_when_disabled_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = True
        monkeypatch.setattr("ai_shell.typeahead.sys.stdin", fake_stdin)
        monkeypatch.setenv("AI_SHELL_NO_TYPEAHEAD", "1")

        with capture_typeahead() as buf:
            assert buf.bytes() == b""
        assert buf.bytes() == b""

    def test_noop_on_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = True
        monkeypatch.setattr("ai_shell.typeahead.sys.stdin", fake_stdin)
        monkeypatch.setattr("ai_shell.typeahead.sys.platform", "win32")

        with capture_typeahead() as buf:
            assert buf.bytes() == b""
