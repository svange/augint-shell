"""Tests for the host-driven ``claude auth login`` flow."""

import sys
from unittest.mock import MagicMock, patch
from urllib.parse import quote

from ai_shell.claude_login import extract_login_url, open_in_chrome, run_piped_login

AUTH_URL = (
    "https://claude.com/cai/oauth/authorize?code=true&client_id=abc&response_type=code"
    "&redirect_uri=https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode%2Fcallback"
    "&scope=user%3Aprofile&code_challenge=xyz&code_challenge_method=S256&state=st4te"
)


def _fake_login_args(expected_code: str = "good#st4te", print_url: bool = True) -> list[str]:
    script = (
        "import sys, time\n"
        "print('Opening browser to sign in…')\n"
        f"url = {AUTH_URL!r}\n"
        f"if {print_url!r}:\n"
        "    print('If the browser didn\\'t open, visit: ' + url)\n"
        "else:\n"
        "    time.sleep(5)\n"
        "sys.stdout.write('Paste code here if prompted > ')\n"
        "sys.stdout.flush()\n"
        "code = sys.stdin.readline().strip()\n"
        f"ok = code == {expected_code!r}\n"
        "print('Login successful' if ok else 'Login failed: That code wasn\\'t accepted.')\n"
        "sys.exit(0 if ok else 1)\n"
    )
    return [sys.executable, "-u", "-c", script]


class TestExtractLoginUrl:
    def test_finds_url_after_prefix_text(self):
        assert extract_login_url(f"If the browser didn't open, visit: {AUTH_URL}") == AUTH_URL

    def test_ignores_lines_without_oauth_url(self):
        assert extract_login_url("Opening browser to sign in…") is None
        assert extract_login_url("see https://example.com/docs") is None


def _chrome_reply(url: str, status: int = 200) -> MagicMock:
    response = MagicMock(status=status)
    response.read.return_value = f'{{"id": "T1", "type": "page", "url": "{url}"}}'.encode()
    return response


class TestOpenInChrome:
    @patch("ai_shell.claude_login.HTTPConnection")
    def test_puts_percent_encoded_url_to_devtools_new_tab(self, mock_conn_cls):
        conn = MagicMock()
        conn.getresponse.return_value = _chrome_reply(AUTH_URL)
        mock_conn_cls.return_value = conn

        assert open_in_chrome(45678, AUTH_URL) is True
        mock_conn_cls.assert_called_once_with("127.0.0.1", 45678, timeout=5)
        method, path = conn.request.call_args[0]
        assert method == "PUT"
        # Raw '&' makes Chrome truncate the URL at the first parameter.
        assert "&" not in path
        assert path == f"/json/new?{quote(AUTH_URL, safe='')}"

    @patch("ai_shell.claude_login.HTTPConnection")
    def test_false_when_chrome_opened_a_truncated_url(self, mock_conn_cls):
        conn = MagicMock()
        conn.getresponse.return_value = _chrome_reply("https://claude.ai/oauth/authorize?code=true")
        mock_conn_cls.return_value = conn

        assert open_in_chrome(45678, AUTH_URL) is False

    @patch("ai_shell.claude_login.HTTPConnection")
    def test_true_when_chrome_reports_a_redirected_host_with_same_params(self, mock_conn_cls):
        conn = MagicMock()
        redirected = AUTH_URL.replace("https://claude.com/cai/", "https://claude.ai/")
        conn.getresponse.return_value = _chrome_reply(redirected)
        mock_conn_cls.return_value = conn

        assert open_in_chrome(45678, AUTH_URL) is True

    @patch("ai_shell.claude_login.HTTPConnection")
    def test_false_when_chrome_refuses(self, mock_conn_cls):
        conn = MagicMock()
        conn.request.side_effect = OSError("refused")
        mock_conn_cls.return_value = conn

        assert open_in_chrome(45678, AUTH_URL) is False


class TestRunPipedLogin:
    def test_opens_url_and_pipes_code(self):
        opened: list[str] = []
        echoed: list[str] = []

        code = run_piped_login(
            _fake_login_args(),
            open_url=lambda url: opened.append(url) or True,
            prompt_code=lambda: " good#st4te \n",
            echo=echoed.append,
        )

        assert code == 0
        assert opened == [AUTH_URL]
        assert any("Login successful" in line for line in echoed)
        # The URL line itself is not echoed (it was handled), other lines are.
        assert not any(AUTH_URL in line for line in echoed)
        assert any("Opening browser" in line for line in echoed)

    def test_bad_code_returns_nonzero_and_echoes_error(self):
        echoed: list[str] = []

        code = run_piped_login(
            _fake_login_args(),
            open_url=lambda url: True,
            prompt_code=lambda: "wrong",
            echo=echoed.append,
        )

        assert code == 1
        assert any("wasn't accepted" in line for line in echoed)

    def test_empty_code_aborts(self):
        code = run_piped_login(
            _fake_login_args(), open_url=lambda url: True, prompt_code=lambda: "   "
        )
        assert code == 1

    def test_returns_none_when_no_url_appears(self):
        code = run_piped_login(
            _fake_login_args(print_url=False),
            open_url=lambda url: True,
            prompt_code=lambda: "never",
            url_timeout=0.5,
        )
        assert code is None
