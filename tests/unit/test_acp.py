"""ai_shell.acp: path mapping, sandbox filters and routing for ACP clients.

The client messages below are shaped on a capture of JetBrains Air in IntelliJ
2026.3 (2026-11-09): ``initialize`` names no project, ``session/new`` carries a
Windows ``cwd`` and a host MCP server (``idea64.exe stdioMcpServer``).
"""

from __future__ import annotations

import io
import json
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from ai_shell import acp
from ai_shell.acp import (
    AcpProxy,
    Backend,
    PathMap,
    ProcessBackend,
    map_strings,
    prepare_session_params,
    probe_initialize,
    pump_backend,
    run_stdio,
    sandbox_client_capabilities,
    stdio_mcp_server,
)

WIN = PathMap(r"C:\Users\me\projects\demo", "/root/projects/demo")
POSIX = PathMap("/home/me/projects/demo", "/root/projects/demo")

AIR_INITIALIZE = {
    "protocolVersion": 1,
    "clientCapabilities": {
        "fs": {"readTextFile": True, "writeTextFile": True},
        "terminal": True,
        "auth": {"terminal": True},
        "elicitation": {"form": {}, "url": {}},
        "_meta": {
            "terminal-auth": True,
            "jetbrains": {"air": {"version": 1, "capabilities": ["diffPatch"]}},
        },
    },
    "clientInfo": {"name": "air-plugin:idea", "version": "263"},
}


def air_session_new(cwd: str = r"C:\Users\me\projects\demo") -> dict:
    return {
        "cwd": cwd,
        "mcpServers": [
            {
                "type": "stdio",
                "name": "jetbrains_air_ide",
                "command": r"C:\Program Files\JetBrains\IntelliJ IDEA\bin\idea64.exe",
                "args": ["stdioMcpServer"],
                "env": [{"name": "IJ_MCP_SERVER_PROJECT_PATH", "value": cwd}],
            }
        ],
        "_meta": {
            "additionalRoots": [
                r"C:\Users\me\AppData\Local\JetBrains\IntelliJIdea2026.3\air-views\x",
                cwd + r"\docs",
            ]
        },
    }


# =============================================================================
# PathMap
# =============================================================================


class TestPathMap:
    def test_windows_root_and_child(self):
        assert WIN.host_to_container(r"C:\Users\me\projects\demo") == "/root/projects/demo"
        assert (
            WIN.host_to_container(r"C:\Users\me\projects\demo\src\a.py")
            == "/root/projects/demo/src/a.py"
        )

    def test_windows_is_case_insensitive_and_takes_forward_slashes(self):
        assert WIN.host_to_container("c:/users/ME/projects/demo/x") == "/root/projects/demo/x"

    def test_windows_sibling_folder_is_not_mapped(self):
        assert WIN.host_to_container(r"C:\Users\me\projects\demo2\x") is None
        assert WIN.host_to_container("plain text") is None

    def test_container_to_windows(self):
        assert (
            WIN.container_to_host("/root/projects/demo/src/a.py")
            == r"C:\Users\me\projects\demo\src\a.py"
        )
        assert WIN.container_to_host("/root/projects/demo") == r"C:\Users\me\projects\demo"
        assert WIN.container_to_host("/root/projects/demo-other") is None
        assert WIN.container_to_host("/etc/passwd") is None

    def test_posix_round_trip(self):
        path = "/home/me/projects/demo/a b.txt"
        assert POSIX.container_to_host(POSIX.host_to_container(path)) == path

    def test_file_uris_windows(self):
        uri = "file:///C:/Users/me/projects/demo/src/a%20b.py"
        mapped = WIN.host_to_container(uri)
        assert mapped == "file:///root/projects/demo/src/a%20b.py"
        assert WIN.container_to_host(mapped) == "file:///C:/Users/me/projects/demo/src/a%20b.py"

    def test_file_uris_posix(self):
        assert (
            POSIX.host_to_container("file:///home/me/projects/demo/x.py")
            == "file:///root/projects/demo/x.py"
        )
        assert (
            POSIX.container_to_host("file:///root/projects/demo/x.py")
            == "file:///home/me/projects/demo/x.py"
        )

    def test_map_strings_walks_nested_values(self):
        value = {"a": [r"C:\Users\me\projects\demo\x", 3, None], "b": {"c": "keep"}}
        assert map_strings(value, WIN.host_to_container) == {
            "a": ["/root/projects/demo/x", 3, None],
            "b": {"c": "keep"},
        }


# =============================================================================
# Filters
# =============================================================================


class TestFilters:
    def test_initialize_turns_off_host_capabilities(self):
        out = sandbox_client_capabilities(AIR_INITIALIZE)
        caps = out["clientCapabilities"]
        assert caps["fs"] == {"readTextFile": False, "writeTextFile": False}
        assert caps["terminal"] is False
        assert "terminal" not in caps["auth"]
        assert "terminal-auth" not in caps["_meta"]
        # Air's own capabilities pass through untouched.
        assert caps["_meta"]["jetbrains"]["air"]["capabilities"] == ["diffPatch"]
        # The input is not changed.
        assert AIR_INITIALIZE["clientCapabilities"]["terminal"] is True

    def test_session_new_maps_cwd_and_replaces_mcp_servers(self):
        chrome = stdio_mcp_server("chrome-devtools", {"command": "cdm", "args": ["--x"]})
        out = prepare_session_params(air_session_new(), WIN, [chrome])
        assert out["cwd"] == "/root/projects/demo"
        assert out["mcpServers"] == [
            {"name": "chrome-devtools", "command": "cdm", "args": ["--x"], "env": []}
        ]
        assert out["_meta"]["additionalRoots"] == ["/root/projects/demo/docs"]

    def test_additional_directories_outside_the_project_are_dropped(self):
        params = {
            "cwd": WIN.host_root,
            "additionalDirectories": [r"D:\elsewhere", WIN.host_root + r"\lib"],
        }
        out = prepare_session_params(params, WIN, [])
        assert out["additionalDirectories"] == ["/root/projects/demo/lib"]
        assert out["mcpServers"] == []

    def test_stdio_mcp_server_converts_env(self):
        assert stdio_mcp_server("n", {"command": "c", "env": {"A": 1}}) == {
            "name": "n",
            "command": "c",
            "args": [],
            "env": [{"name": "A", "value": "1"}],
        }


# =============================================================================
# Router
# =============================================================================


class FakeBackend(Backend):
    """Records what the proxy sends; answers initialize like an adapter would."""

    def __init__(self, proxy_ref, label, pathmap, extra=None):
        super().__init__(label, pathmap, extra or [])
        self.proxy_ref = proxy_ref
        self.sent: list[dict] = []
        self.closed = False

    def send(self, msg):
        self.sent.append(msg)
        if msg.get("method") == "initialize":
            self.proxy_ref["proxy"].handle_backend(
                self, {"jsonrpc": "2.0", "id": msg["id"], "result": {"protocolVersion": 1}}
            )

    def close(self):
        self.closed = True


@pytest.fixture
def harness():
    out: list[dict] = []
    ref: dict = {}
    started: list[FakeBackend] = []
    roots = {
        r"C:\Users\me\projects\demo": "/root/projects/demo",
        r"C:\Users\me\projects\other": "/root/projects/other",
    }

    def factory(cwd):
        backend = FakeBackend(
            ref, f"box-{len(started)}", PathMap(cwd, roots[cwd]), [{"name": "extra"}]
        )
        started.append(backend)
        return backend

    probe_calls: list[dict] = []

    def probe(params):
        probe_calls.append(params)
        return {"protocolVersion": 1, "agentInfo": {"name": "probe"}}

    proxy = AcpProxy(write_client=out.append, backend_factory=factory, probe=probe)
    ref["proxy"] = proxy
    return proxy, out, started, probe_calls


def _init(proxy):
    proxy.handle_client(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": AIR_INITIALIZE}
    )


class TestRouter:
    def test_initialize_is_answered_by_the_probe_without_a_backend(self, harness):
        proxy, out, started, probe_calls = harness
        _init(proxy)
        assert started == []
        assert out == [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"protocolVersion": 1, "agentInfo": {"name": "probe"}},
            }
        ]
        assert probe_calls[0]["clientCapabilities"]["terminal"] is False

    def test_session_new_starts_a_backend_and_replays_initialize(self, harness):
        proxy, out, started, _ = harness
        _init(proxy)
        proxy.handle_client(
            {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": air_session_new()}
        )
        backend = started[0]
        init, new = backend.sent
        assert init["method"] == "initialize"
        assert init["params"]["clientCapabilities"]["fs"]["writeTextFile"] is False
        assert new["id"] == 2
        assert new["params"]["cwd"] == "/root/projects/demo"
        assert new["params"]["mcpServers"] == [{"name": "extra"}]
        # The replayed initialize's answer is not sent to the client.
        assert len(out) == 1

        proxy.handle_backend(backend, {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "s1"}})
        assert out[-1] == {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "s1"}}

        proxy.handle_client(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "session/prompt",
                "params": {
                    "sessionId": "s1",
                    "prompt": [
                        {
                            "type": "resource_link",
                            "uri": "file:///C:/Users/me/projects/demo/README.md",
                        }
                    ],
                },
            }
        )
        assert (
            backend.sent[-1]["params"]["prompt"][0]["uri"] == "file:///root/projects/demo/README.md"
        )

    def test_agent_paths_are_mapped_back_for_the_client(self, harness):
        proxy, out, started, _ = harness
        _init(proxy)
        proxy.handle_client(
            {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": air_session_new()}
        )
        backend = started[0]
        proxy.handle_backend(
            backend,
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "s1",
                    "update": {
                        "sessionUpdate": "tool_call",
                        "locations": [{"path": "/root/projects/demo/src/a.py", "line": 3}],
                    },
                },
            },
        )
        assert (
            out[-1]["params"]["update"]["locations"][0]["path"]
            == r"C:\Users\me\projects\demo\src\a.py"
        )

    def test_agent_requests_get_proxy_ids_and_answers_go_back(self, harness):
        proxy, out, started, _ = harness
        _init(proxy)
        proxy.handle_client(
            {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": air_session_new()}
        )
        backend = started[0]
        proxy.handle_backend(
            backend,
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "session/request_permission",
                "params": {"sessionId": "s1"},
            },
        )
        forwarded = out[-1]
        assert forwarded["method"] == "session/request_permission"
        assert forwarded["id"] != 0
        proxy.handle_client(
            {"jsonrpc": "2.0", "id": forwarded["id"], "result": {"outcome": "allow"}}
        )
        assert backend.sent[-1] == {"jsonrpc": "2.0", "id": 0, "result": {"outcome": "allow"}}

    def test_two_projects_get_two_backends_and_sessions_route_apart(self, harness):
        proxy, out, started, _ = harness
        _init(proxy)
        proxy.handle_client(
            {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": air_session_new()}
        )
        proxy.handle_backend(started[0], {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "a"}})
        proxy.handle_client(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "session/new",
                "params": air_session_new(r"C:\Users\me\projects\other"),
            }
        )
        proxy.handle_backend(started[1], {"jsonrpc": "2.0", "id": 3, "result": {"sessionId": "b"}})
        assert len(started) == 2
        assert started[1].sent[-1]["params"]["cwd"] == "/root/projects/other"

        proxy.handle_client(
            {"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": "a"}}
        )
        assert started[0].sent[-1]["method"] == "session/cancel"
        assert started[1].sent[-1]["method"] == "session/new"

    def test_same_project_reuses_its_backend(self, harness):
        proxy, out, started, _ = harness
        _init(proxy)
        for ident in (2, 3):
            proxy.handle_client(
                {
                    "jsonrpc": "2.0",
                    "id": ident,
                    "method": "session/new",
                    "params": air_session_new(),
                }
            )
        assert len(started) == 1

    def test_unknown_session_gets_an_error(self, harness):
        proxy, out, started, _ = harness
        _init(proxy)
        proxy.handle_client(
            {"jsonrpc": "2.0", "id": 9, "method": "session/prompt", "params": {"sessionId": "nope"}}
        )
        assert out[-1]["error"]["code"] == acp.INVALID_PARAMS

    def test_session_new_before_initialize_gets_an_error(self, harness):
        proxy, out, started, _ = harness
        proxy.handle_client(
            {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": air_session_new()}
        )
        assert out[-1]["error"]["code"] == acp.INTERNAL_ERROR
        assert started == []

    def test_a_failed_start_answers_the_client(self, harness):
        proxy, out, started, _ = harness
        _init(proxy)

        def boom(cwd):
            raise RuntimeError("docker is not running")

        proxy.backend_factory = boom
        proxy.handle_client(
            {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": air_session_new()}
        )
        assert "docker is not running" in out[-1]["error"]["message"]

    def test_backend_exit_fails_pending_requests_and_restarts_later(self, harness):
        proxy, out, started, _ = harness
        _init(proxy)
        proxy.handle_client(
            {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": air_session_new()}
        )
        proxy.backend_exited(started[0])
        assert out[-1]["id"] == 2
        assert "stopped" in out[-1]["error"]["message"]
        proxy.handle_client(
            {"jsonrpc": "2.0", "id": 3, "method": "session/new", "params": air_session_new()}
        )
        assert len(started) == 2


# =============================================================================
# Processes (a fake adapter in Python, no Docker)
# =============================================================================

FAKE_ADAPTER = r"""
import json, sys
for line in sys.stdin:
    msg = json.loads(line)
    m, i = msg.get("method"), msg.get("id")
    if m == "initialize":
        out = {"jsonrpc": "2.0", "id": i, "result": {"protocolVersion": 1, "agentInfo": {"name": "fake"}}}
    elif m == "session/new":
        cwd = msg["params"]["cwd"]
        if not cwd.startswith("/"):
            out = {"jsonrpc": "2.0", "id": i, "error": {"code": -32602, "message": "cwd must be absolute"}}
        else:
            out = {"jsonrpc": "2.0", "id": i, "result": {"sessionId": "s-" + cwd}}
    else:
        continue
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()
"""


@pytest.fixture
def fake_adapter(tmp_path):
    script = tmp_path / "fake_adapter.py"
    script.write_text(FAKE_ADAPTER)
    return [sys.executable, "-I", str(script)]


def test_probe_initialize_reads_the_adapter_answer(fake_adapter):
    assert probe_initialize(fake_adapter, {})["agentInfo"] == {"name": "fake"}


def test_probe_initialize_fails_when_the_adapter_exits(tmp_path):
    with pytest.raises(RuntimeError, match="did not answer"):
        probe_initialize([sys.executable, "-c", "pass"], {}, timeout=10)


def test_run_stdio_end_to_end(fake_adapter):
    """A Windows cwd reaches the adapter as a container path, and the session id comes back."""
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": AIR_INITIALIZE},
        {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": air_session_new()},
    ]
    client_out = io.BytesIO()
    done = threading.Event()
    backends: list[ProcessBackend] = []

    class SlowInput(io.BytesIO):
        """Holds stdin open until the session answer arrives, like a real client."""

        def __iter__(self):
            for msg in lines:
                yield (json.dumps(msg) + "\n").encode()
                time.sleep(0.2)
            done.wait(20)

    def make_proxy(write_client):
        ref: dict = {}

        def write(msg):
            write_client(msg)
            if msg.get("id") == 2:
                done.set()

        def factory(cwd):
            backend = ProcessBackend("fake", PathMap(cwd, "/root/projects/demo"), fake_adapter)
            backends.append(backend)
            pump_backend(ref["proxy"], backend)
            return backend

        proxy = AcpProxy(
            write_client=write, backend_factory=factory, probe=lambda p: {"protocolVersion": 1}
        )
        ref["proxy"] = proxy
        return proxy

    run_stdio(make_proxy, SlowInput(), client_out)
    answers = [json.loads(line) for line in client_out.getvalue().decode().splitlines()]
    assert answers[0]["id"] == 1
    assert answers[-1] == {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {"sessionId": "s-/root/projects/demo"},
    }
    # The client closing stdin stops the backend.
    assert not backends[0].alive


# =============================================================================
# CLI module
# =============================================================================


class TestCliModule:
    def test_adapter_shell_commands(self):
        from ai_shell.cli.commands.acp import ADAPTERS

        claude = ADAPTERS["claude"].shell_command()
        assert claude[:2] == ["sh", "-c"]
        assert "npm install -g @agentclientprotocol/claude-agent-acp" in claude[2]
        assert claude[2].endswith("exec claude-agent-acp")
        assert ADAPTERS["opencode"].shell_command() == ["sh", "-c", "exec opencode acp"]

    def test_probe_argv_runs_the_image_without_its_entrypoint(self):
        from ai_shell.cli.commands.acp import probe_argv

        argv = probe_argv("svange/augint-shell:latest", "codex")
        assert argv[:5] == ["docker", "run", "--rm", "-i", "--entrypoint"]
        assert argv[5] == ""
        assert "svange/augint-shell:latest" in argv
        assert "-v" not in argv  # no project, no home mounts

    def test_acp_is_registered_with_three_tools(self):
        from ai_shell.cli.__main__ import cli

        result = CliRunner().invoke(cli, ["acp", "--help"])
        assert result.exit_code == 0
        for tool in ("claude", "codex", "opencode"):
            assert tool in result.output

    def test_claude_takes_account_and_local_chrome(self):
        from ai_shell.cli.__main__ import cli

        result = CliRunner().invoke(cli, ["acp", "claude", "--help"])
        assert "--account" in result.output
        assert "--local-chrome" in result.output

    def test_start_backend_builds_a_docker_exec(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock, patch

        from ai_shell.cli.commands import acp as acp_cli

        project = tmp_path / "demo"
        project.mkdir()
        config = MagicMock()
        config.project_name = "demo"
        config.project_dir = project
        config.claude_account = ""
        config.claude_provider = "anthropic"
        manager = MagicMock()
        manager.ensure_dev_container.return_value = "augint-shell-demo-dev"
        manager.exec_args.side_effect = lambda *a, **k: ["docker", "exec", "-i", "fake"]
        with (
            patch.object(acp_cli, "load_config", return_value=config),
            patch("ai_shell.container.ContainerManager", return_value=manager),
            patch.object(acp_cli, "_tool_env", return_value=({"A": "1"}, ["env", "-u", "X"], "")),
            patch.object(acp_cli, "_chrome_mcp_servers", return_value=[]),
            patch.object(acp, "ProcessBackend") as backend_cls,
        ):
            acp_cli.start_backend(str(project), acp_cli.AcpOptions(tool="claude"))
        args, kwargs = manager.exec_args.call_args
        assert args[0] == "augint-shell-demo-dev"
        assert args[1][:3] == ["env", "-u", "X"]
        assert kwargs == {"extra_env": {"A": "1"}, "workdir": "/root/projects/demo", "stdin": True}
        pathmap = backend_cls.call_args[0][1]
        assert pathmap == PathMap(str(Path(project).resolve()), "/root/projects/demo")

    def test_start_backend_rejects_a_missing_folder(self, tmp_path):
        from ai_shell.cli.commands.acp import AcpOptions, start_backend

        with pytest.raises(ValueError, match="not a folder"):
            start_backend(str(tmp_path / "missing"), AcpOptions(tool="codex"))


# =============================================================================
# Sign-in only when the login needs it
# =============================================================================

LOGIN = acp.terminal_login_method(
    "ai-shell-login", "Sign in (sam)", r"C:\bin\ai-shell.exe", ["acp", "login", "--account", "sam"]
)


@pytest.fixture
def login_harness(harness):
    proxy, out, started, _ = harness
    proxy.login_method = LOGIN
    state = {"needs": False, "checks": 0, "prepared": 0}
    real_factory = proxy.backend_factory

    def factory(cwd):
        backend = real_factory(cwd)

        def needs_login():
            state["checks"] += 1
            return state["needs"]

        def prepare():
            state["prepared"] += 1

        backend.needs_login = needs_login
        backend.prepare_session = prepare
        return backend

    proxy.backend_factory = factory
    return proxy, out, started, state


def _new(proxy, ident):
    proxy.handle_client(
        {"jsonrpc": "2.0", "id": ident, "method": "session/new", "params": air_session_new()}
    )


def _authenticate(proxy, ident, method_id="ai-shell-login"):
    proxy.handle_client(
        {"jsonrpc": "2.0", "id": ident, "method": "authenticate", "params": {"methodId": method_id}}
    )


class TestLogin:
    def test_terminal_login_method_has_both_forms(self):
        assert LOGIN["type"] == "terminal"
        assert LOGIN["args"] == ["acp", "login", "--account", "sam"]
        assert LOGIN["_meta"]["terminal-auth"]["command"] == r"C:\bin\ai-shell.exe"
        assert LOGIN["_meta"]["terminal-auth"]["args"] == LOGIN["args"]

    def test_login_method_is_offered_to_a_client_that_runs_terminal_sign_ins(self, login_harness):
        proxy, out, _, _ = login_harness
        _init(proxy)
        assert out[0]["result"]["authMethods"] == [LOGIN]

    def test_login_method_is_not_offered_otherwise(self, login_harness):
        proxy, out, _, _ = login_harness
        params = {"protocolVersion": 1, "clientCapabilities": {"fs": {}}}
        proxy.handle_client({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params})
        assert "authMethods" not in out[0]["result"]

    def test_good_login_starts_the_session_without_a_prompt(self, login_harness):
        proxy, out, started, state = login_harness
        _init(proxy)
        _new(proxy, 2)
        assert state["checks"] == 1
        assert started[0].sent[-1]["method"] == "session/new"
        assert len(out) == 1  # no error went to the client

    def test_expired_login_answers_auth_required(self, login_harness):
        proxy, out, started, state = login_harness
        state["needs"] = True
        _init(proxy)
        _new(proxy, 2)
        assert out[-1]["error"]["code"] == acp.AUTH_REQUIRED
        assert "acp login --account sam" in out[-1]["error"]["message"]
        # The session was not sent on, and Chrome was not attached.
        assert started[0].sent[-1]["method"] == "initialize"
        assert state["prepared"] == 0

    def test_authenticate_after_the_sign_in_lets_the_retry_through(self, login_harness):
        proxy, out, started, state = login_harness
        state["needs"] = True
        _init(proxy)
        _new(proxy, 2)
        state["needs"] = False  # the user signed in in the terminal
        _authenticate(proxy, 3)
        assert out[-1] == {"jsonrpc": "2.0", "id": 3, "result": {}}
        _new(proxy, 4)
        assert started[0].sent[-1]["id"] == 4
        assert state["prepared"] == 1

    def test_authenticate_while_still_signed_out_fails(self, login_harness):
        proxy, out, _, state = login_harness
        state["needs"] = True
        _init(proxy)
        _new(proxy, 2)
        _authenticate(proxy, 3)
        assert out[-1]["error"]["code"] == acp.AUTH_REQUIRED

    def test_chrome_is_attached_once_and_again_after_a_sign_in(self, login_harness):
        proxy, out, started, state = login_harness
        _init(proxy)
        _new(proxy, 2)
        _new(proxy, 3)
        assert state["prepared"] == 1
        _authenticate(proxy, 4)
        _new(proxy, 5)
        assert state["prepared"] == 2

    def test_other_auth_methods_go_to_the_agent(self, login_harness):
        proxy, out, started, _ = login_harness
        _init(proxy)
        _new(proxy, 2)
        _authenticate(proxy, 3, "gateway")
        assert started[0].sent[-1]["method"] == "authenticate"


class TestLoginStatus:
    NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)

    @staticmethod
    def _status(**fields):
        return json.dumps({"loggedIn": True, "authMethod": "claude.ai", **fields})

    def test_valid_login(self):
        from ai_shell.cli.commands.acp import status_needs_login

        status = self._status(loginExpiresAt="2026-12-07T11:21:07.561Z")
        assert not status_needs_login(0, status, self.NOW)

    def test_expired_or_about_to_expire(self):
        from ai_shell.cli.commands.acp import status_needs_login

        assert status_needs_login(0, self._status(loginExpiresAt="2026-11-09T11:00:00Z"), self.NOW)
        assert status_needs_login(0, self._status(loginExpiresAt="2026-11-09T12:05:00Z"), self.NOW)

    def test_logged_out_or_unreadable(self):
        from ai_shell.cli.commands.acp import status_needs_login

        assert status_needs_login(1, "", self.NOW)
        assert status_needs_login(0, json.dumps({"loggedIn": False}), self.NOW)
        assert status_needs_login(0, "not json", self.NOW)

    def test_no_expiry_field_is_fine(self):
        from ai_shell.cli.commands.acp import status_needs_login

        assert not status_needs_login(0, self._status(), self.NOW)

    def test_uses_login(self):
        from ai_shell.cli.commands.acp import uses_login

        config = MagicMock(claude_provider="anthropic")
        assert uses_login({}, config)
        assert uses_login({"CLAUDE_CONFIG_DIR": "/x", "ANTHROPIC_API_KEY": "k"}, config)
        assert not uses_login({"CLAUDE_CODE_OAUTH_TOKEN": "t"}, config)
        assert not uses_login({"ANTHROPIC_API_KEY": "k"}, config)
        assert not uses_login({}, MagicMock(claude_provider="aws"))

    def test_login_args(self):
        from ai_shell.cli.commands.acp import AcpOptions, login_args

        assert login_args(AcpOptions(tool="claude")) == ["acp", "login"]
        opts = AcpOptions(tool="claude", account="mike", local_chrome=True)
        assert login_args(opts) == ["acp", "login", "--account", "mike", "--local-chrome"]

    def test_login_folder_is_remembered_per_account(self, tmp_path):
        from ai_shell.cli.commands.acp import remember_login_folder, remembered_login_folder

        remember_login_folder("mike", tmp_path)
        assert remembered_login_folder("mike") == tmp_path
        assert remembered_login_folder("adam") is None


class TestLoginCommand:
    @staticmethod
    def _invoke(tmp_path, needed, args):
        from ai_shell.cli.__main__ import cli
        from ai_shell.cli.commands import acp as acp_cli

        config = MagicMock(project_name="demo", project_dir=tmp_path, claude_account="")
        manager = MagicMock()
        manager.ensure_dev_container.return_value = "box"
        with (
            patch.object(acp_cli, "load_config", return_value=config),
            patch("ai_shell.container.ContainerManager", return_value=manager),
            patch("ai_shell.cli.commands.tools._claude_exec_env", return_value={}),
            patch.object(acp_cli, "login_needed", return_value=needed),
            patch("ai_shell.cli.commands.tools._ensure_claude_login") as login,
            patch("ai_shell.cli.commands.tools._plain_chrome_login") as chrome_login,
        ):
            result = CliRunner().invoke(
                cli, ["acp", "login", *args, "--project-dir", str(tmp_path)]
            )
        assert result.exit_code == 0, result.output
        return login, chrome_login

    def test_skips_a_good_login(self, tmp_path):
        login, chrome_login = self._invoke(tmp_path, False, [])
        login.assert_not_called()
        chrome_login.assert_not_called()

    def test_signs_in_when_needed(self, tmp_path):
        login, chrome_login = self._invoke(tmp_path, True, ["--no-local-chrome"])
        assert login.call_args.kwargs["force"] is True
        assert login.call_args.kwargs["workdir"] == "/root/projects/demo"
        chrome_login.assert_not_called()
