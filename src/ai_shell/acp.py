"""ACP proxy: run an ACP agent in the dev container for an ACP client on the host.

ACP (Agent Client Protocol) is JSON-RPC over stdio between a client (JetBrains
Air, Zed) and an agent. The client and the agent see the project at different
paths: the client sends the host path (``C:\\Users\\me\\projects\\x``), and the
agent runs in the dev container, where the project is ``/root/projects/x``.
Every path in the protocol is absolute, so this proxy swaps the project root in
both directions. The bind mount keeps everything below the root the same.

The proxy also keeps the agent inside the container:

- It removes the client's ``fs``, ``terminal`` and terminal-auth capabilities
  from ``initialize``, so the agent never asks the client to read, write or run
  anything on the host.
- It drops the MCP servers the client offers in ``session/new``. They are host
  commands (JetBrains sends ``idea64.exe stdioMcpServer``) and cannot run in the
  container. ai-shell adds its own servers (the Chrome DevTools MCP) instead.

The client sends ``initialize`` before it names a project, and it starts the
agent in its own data folder, not the project. So the proxy answers
``initialize`` from a short run of the adapter in the image (``probe``), and
starts one backend (``docker exec -i`` of the adapter) per project, when a
``session/new`` names that project's folder. Each backend gets the client's
``initialize`` replayed first.

Nothing here knows about Click or the container manager; the CLI module wires
the backend factory and the probe.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import IO, Any
from urllib.parse import quote, unquote

logger = logging.getLogger(__name__)

JsonObj = dict[str, Any]

# JSON-RPC error codes the proxy answers with.
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

BACKEND_START_TIMEOUT = 180.0

_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_FILE_URI_RE = re.compile(r"^file://", re.IGNORECASE)


# =============================================================================
# Path mapping
# =============================================================================


def _is_windows_path(path: str) -> bool:
    return bool(_DRIVE_RE.match(path)) or path.startswith("\\\\")


@dataclass(frozen=True)
class PathMap:
    """One project root on the host and the same folder in the container."""

    host_root: str
    container_root: str

    @property
    def _windows(self) -> bool:
        return _is_windows_path(self.host_root)

    def _host_rest(self, value: str) -> str | None:
        """The part of *value* below the host root, with ``/`` separators."""
        root = self.host_root.rstrip("\\/")
        if self._windows:
            norm_value = value.replace("/", "\\")
            norm_root = root.replace("/", "\\")
            if norm_value.lower() == norm_root.lower():
                return ""
            if norm_value.lower().startswith(norm_root.lower() + "\\"):
                return norm_value[len(norm_root) + 1 :].replace("\\", "/")
            return None
        if value == root:
            return ""
        if value.startswith(root + "/"):
            return value[len(root) + 1 :]
        return None

    def _container_rest(self, value: str) -> str | None:
        root = self.container_root.rstrip("/")
        if value == root:
            return ""
        if value.startswith(root + "/"):
            return value[len(root) + 1 :]
        return None

    def host_to_container(self, value: str) -> str | None:
        """Map a host path or ``file://`` URI; ``None`` when it is outside the project."""
        if _FILE_URI_RE.match(value):
            path = unquote(value[len("file://") :])
            if re.match(r"^/[A-Za-z]:[\\/]", path):
                path = path[1:]
            rest = self._host_rest(path)
            if rest is None:
                return None
            mapped = self.container_root.rstrip("/") + ("/" + rest if rest else "")
            return "file://" + quote(mapped, safe="/")
        rest = self._host_rest(value)
        if rest is None:
            return None
        return self.container_root.rstrip("/") + ("/" + rest if rest else "")

    def container_to_host(self, value: str) -> str | None:
        """Map a container path or ``file://`` URI; ``None`` when it is outside the project."""
        if _FILE_URI_RE.match(value):
            rest = self._container_rest(unquote(value[len("file://") :]))
            if rest is None:
                return None
            host = self._join_host(rest).replace("\\", "/")
            prefix = "file:///" if self._windows else "file://"
            return prefix + quote(host.lstrip("/") if self._windows else host, safe="/:")
        rest = self._container_rest(value)
        if rest is None:
            return None
        return self._join_host(rest)

    def _join_host(self, rest: str) -> str:
        root = self.host_root.rstrip("\\/")
        if not rest:
            return root
        if self._windows:
            return root + "\\" + rest.replace("/", "\\")
        return root + "/" + rest

    def is_container_path(self, value: str) -> bool:
        return self._container_rest(value) is not None


def map_strings(value: Any, fn: Callable[[str], str | None]) -> Any:
    """Return *value* with every string that *fn* maps replaced; other values unchanged."""
    if isinstance(value, str):
        mapped = fn(value)
        return value if mapped is None else mapped
    if isinstance(value, list):
        return [map_strings(item, fn) for item in value]
    if isinstance(value, dict):
        return {key: map_strings(item, fn) for key, item in value.items()}
    return value


# =============================================================================
# Message filters
# =============================================================================


def sandbox_client_capabilities(params: JsonObj) -> JsonObj:
    """``initialize`` params with the host-side client capabilities turned off."""
    out = copy.deepcopy(params)
    caps = out.get("clientCapabilities")
    if not isinstance(caps, dict):
        return out
    caps["fs"] = {"readTextFile": False, "writeTextFile": False}
    caps["terminal"] = False
    auth = caps.get("auth")
    if isinstance(auth, dict):
        auth.pop("terminal", None)
    meta = caps.get("_meta")
    if isinstance(meta, dict):
        # The adapter would offer a sign-in that the client runs in a host terminal.
        meta.pop("terminal-auth", None)
    return out


SESSION_SETUP_METHODS = frozenset({"session/new", "session/load", "session/resume", "session/fork"})


def prepare_session_params(
    params: JsonObj,
    pathmap: PathMap,
    extra_mcp_servers: list[JsonObj],
) -> JsonObj:
    """Map paths for the container and swap the client's MCP servers for ai-shell's."""
    out = map_strings(params, pathmap.host_to_container)
    if not isinstance(out, dict):  # pragma: no cover - params is always an object
        return params
    dropped = [
        server.get("name", "?")
        for server in out.get("mcpServers") or []
        if isinstance(server, dict)
    ]
    if dropped:
        logger.info("Not passing the client's MCP servers into the container: %s", dropped)
    out["mcpServers"] = copy.deepcopy(extra_mcp_servers)
    # Folders outside the project do not exist in the container.
    dirs = out.get("additionalDirectories")
    if isinstance(dirs, list):
        out["additionalDirectories"] = [
            d for d in dirs if isinstance(d, str) and pathmap.is_container_path(d)
        ]
    meta = out.get("_meta")
    if isinstance(meta, dict) and isinstance(meta.get("additionalRoots"), list):
        meta["additionalRoots"] = [
            d
            for d in meta["additionalRoots"]
            if isinstance(d, str) and pathmap.is_container_path(d)
        ]
    return out


def stdio_mcp_server(name: str, spec: JsonObj) -> JsonObj:
    """An ACP ``McpServer`` (stdio) from a Claude-style ``{command, args, env}`` spec."""
    env = spec.get("env") or {}
    return {
        "name": name,
        "command": spec["command"],
        "args": list(spec.get("args") or []),
        "env": [{"name": k, "value": str(v)} for k, v in env.items()],
    }


# =============================================================================
# Backends
# =============================================================================


class Backend:
    """One adapter process in one dev container, for one project."""

    def __init__(self, label: str, pathmap: PathMap, extra_mcp_servers: list[JsonObj]) -> None:
        self.label = label
        self.pathmap = pathmap
        self.extra_mcp_servers = extra_mcp_servers
        self.alive = True

    def send(self, msg: JsonObj) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - interface
        pass


class ProcessBackend(Backend):
    """A backend that talks to a subprocess (``docker exec -i ...``) over stdio."""

    def __init__(
        self,
        label: str,
        pathmap: PathMap,
        argv: list[str],
        extra_mcp_servers: list[JsonObj] | None = None,
    ) -> None:
        super().__init__(label, pathmap, extra_mcp_servers or [])
        logger.debug("acp backend %s: %s", label, " ".join(argv))
        self.proc = subprocess.Popen(  # noqa: S603 - argv built by ai-shell
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
        )
        self._lock = threading.Lock()

    def send(self, msg: JsonObj) -> None:
        data = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        with self._lock:
            assert self.proc.stdin is not None
            self.proc.stdin.write(data)
            self.proc.stdin.flush()

    def lines(self) -> Iterator[bytes]:
        assert self.proc.stdout is not None
        yield from self.proc.stdout

    def close(self) -> None:
        self.alive = False
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.terminate()
        except OSError:
            pass


def probe_initialize(argv: list[str], params: JsonObj, timeout: float = 120.0) -> JsonObj:
    """Run the adapter once (``argv``), send ``initialize``, return its result.

    The result of ``initialize`` names the adapter's capabilities; it does not
    depend on the project, so a run without one answers it.
    """
    proc = subprocess.Popen(  # noqa: S603 - argv built by ai-shell
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr
    )
    result: dict[str, Any] = {}

    def read() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if isinstance(msg, dict) and msg.get("id") == "probe-init":
                result["msg"] = msg
                return

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        assert proc.stdin is not None
        request = {"jsonrpc": "2.0", "id": "probe-init", "method": "initialize", "params": params}
        proc.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
        proc.stdin.flush()
        reader.join(timeout)
    finally:
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        proc.kill()
    msg = result.get("msg")
    if msg is None:
        raise RuntimeError("the agent did not answer initialize")
    if "error" in msg:
        raise RuntimeError(f"the agent refused initialize: {msg['error']}")
    return dict(msg.get("result") or {})


# =============================================================================
# Router
# =============================================================================


@dataclass
class _Pending:
    backend: Backend
    method: str


@dataclass
class AcpProxy:
    """Routes one ACP client to one backend per project.

    *write_client* sends a message to the client. *backend_factory* starts the
    backend for a host folder (the ``cwd`` of a session). *probe* answers
    ``initialize`` before any backend exists.
    """

    write_client: Callable[[JsonObj], None]
    backend_factory: Callable[[str], Backend]
    probe: Callable[[JsonObj], JsonObj]
    folder_key: Callable[[str], str] = field(default=lambda p: p)

    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        self._init_params: JsonObj | None = None
        self._backends: dict[str, Backend] = {}
        self._start_locks: dict[str, threading.Lock] = {}
        self._sessions: dict[str, Backend] = {}
        self._pending: dict[Any, _Pending] = {}
        # Agent-to-client requests get proxy ids, so two backends never collide.
        self._agent_requests: dict[str, tuple[Backend, Any]] = {}
        self._next_agent_id = 0
        self._init_waiters: dict[int, threading.Event] = {}
        self._init_results: dict[int, JsonObj] = {}
        self._last_backend: Backend | None = None

    # -- client side ----------------------------------------------------------

    def handle_client(self, msg: JsonObj) -> None:
        method = msg.get("method")
        has_id = "id" in msg
        if method is None and has_id:
            self._client_response(msg)
            return
        if method is None:
            return
        try:
            if method == "initialize" and has_id:
                self._initialize(msg)
                return
            backend = self._route(method, msg.get("params") or {})
        except Exception as exc:  # noqa: BLE001 - every failure goes back to the client
            logger.warning("acp: %s failed: %s", method, exc)
            if has_id:
                self._error(msg["id"], INTERNAL_ERROR, f"ai-shell: {exc}")
            return
        if backend is None:
            if has_id:
                self._error(
                    msg["id"], INVALID_PARAMS, f"ai-shell: no session for {method}; open one first"
                )
            return
        params = msg.get("params")
        if method in SESSION_SETUP_METHODS and isinstance(params, dict):
            params = prepare_session_params(params, backend.pathmap, backend.extra_mcp_servers)
        else:
            params = map_strings(params, backend.pathmap.host_to_container)
        out = dict(msg)
        if params is not None:
            out["params"] = params
        if has_id:
            with self._lock:
                self._pending[msg["id"]] = _Pending(backend, method)
            if method in {"session/load", "session/resume"} and isinstance(params, dict):
                sid = params.get("sessionId")
                if isinstance(sid, str):
                    with self._lock:
                        self._sessions[sid] = backend
        backend.send(out)

    def _initialize(self, msg: JsonObj) -> None:
        params = sandbox_client_capabilities(msg.get("params") or {})
        with self._lock:
            self._init_params = params
        result = self.probe(params)
        self.write_client({"jsonrpc": "2.0", "id": msg["id"], "result": result})

    def _route(self, method: str, params: JsonObj) -> Backend | None:
        cwd = params.get("cwd") if isinstance(params, dict) else None
        if method in SESSION_SETUP_METHODS or (method == "session/list" and cwd):
            if not isinstance(cwd, str) or not cwd:
                raise ValueError(f"{method} needs a cwd")
            return self._backend_for(cwd)
        sid = params.get("sessionId") if isinstance(params, dict) else None
        with self._lock:
            if isinstance(sid, str):
                return self._sessions.get(sid)
            if method == "$/cancel_request":
                pending = self._pending.get(params.get("requestId"))
                return pending.backend if pending else None
            return self._last_backend

    def _backend_for(self, cwd: str) -> Backend:
        key = self.folder_key(cwd)
        with self._lock:
            start_lock = self._start_locks.setdefault(key, threading.Lock())
        # One start per folder at a time: two sessions opened together share it.
        with start_lock:
            with self._lock:
                backend = self._backends.get(key)
                if backend is not None and backend.alive:
                    self._last_backend = backend
                    return backend
                init_params = self._init_params
            if init_params is None:
                raise ValueError("initialize must come first")
            backend = self.backend_factory(cwd)
            self._replay_initialize(backend, init_params)
            with self._lock:
                self._backends[key] = backend
                self._last_backend = backend
            return backend

    def _replay_initialize(self, backend: Backend, params: JsonObj) -> None:
        with self._lock:
            self._next_agent_id += 1
            ident = self._next_agent_id
            event = threading.Event()
            self._init_waiters[ident] = event
        backend.send(
            {
                "jsonrpc": "2.0",
                "id": f"ai-shell-init-{ident}",
                "method": "initialize",
                "params": params,
            }
        )
        if not event.wait(BACKEND_START_TIMEOUT):
            backend.close()
            raise RuntimeError(f"{backend.label}: the agent did not answer initialize")
        with self._lock:
            result = self._init_results.pop(ident, {})
        if not result:
            backend.close()
            raise RuntimeError(f"{backend.label}: the agent stopped before it answered initialize")
        if "error" in result:
            backend.close()
            raise RuntimeError(f"{backend.label}: initialize failed: {result['error']}")

    def _client_response(self, msg: JsonObj) -> None:
        with self._lock:
            entry = self._agent_requests.pop(str(msg["id"]), None)
        if entry is None:
            return
        backend, original_id = entry
        out = map_strings(msg, backend.pathmap.host_to_container)
        out["id"] = original_id
        backend.send(out)

    def _error(self, ident: Any, code: int, message: str) -> None:
        self.write_client(
            {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": message}}
        )

    # -- agent side -----------------------------------------------------------

    def handle_backend(self, backend: Backend, msg: JsonObj) -> None:
        method = msg.get("method")
        ident = msg.get("id")
        if method is None and ident is not None:
            if isinstance(ident, str) and ident.startswith("ai-shell-init-"):
                num = int(ident.rsplit("-", 1)[1])
                with self._lock:
                    self._init_results[num] = msg
                    waiter = self._init_waiters.pop(num, None)
                if waiter:
                    waiter.set()
                return
            with self._lock:
                pending = self._pending.pop(ident, None)
            if pending is None:
                return
            out = map_strings(msg, backend.pathmap.container_to_host)
            if pending.method in {"session/new", "session/fork"}:
                sid = (msg.get("result") or {}).get("sessionId")
                if isinstance(sid, str):
                    with self._lock:
                        self._sessions[sid] = backend
            self.write_client(out)
            return
        out = map_strings(msg, backend.pathmap.container_to_host)
        if ident is not None:
            with self._lock:
                self._next_agent_id += 1
                proxy_id = f"ai-shell-{self._next_agent_id}"
                self._agent_requests[proxy_id] = (backend, ident)
            out["id"] = proxy_id
        self.write_client(out)

    def backend_exited(self, backend: Backend) -> None:
        """Fail what the backend still owed and forget it, so the next session restarts it."""
        backend.alive = False
        with self._lock:
            owed = [ident for ident, p in self._pending.items() if p.backend is backend]
            for ident in owed:
                del self._pending[ident]
            for sid in [s for s, b in self._sessions.items() if b is backend]:
                del self._sessions[sid]
            for key in [k for k, b in self._backends.items() if b is backend]:
                del self._backends[key]
            for pid in [p for p, (b, _) in self._agent_requests.items() if b is backend]:
                del self._agent_requests[pid]
            if self._last_backend is backend:
                self._last_backend = None
            waiters = list(self._init_waiters.values())
        for ident in owed:
            self._error(ident, INTERNAL_ERROR, f"ai-shell: the agent in {backend.label} stopped")
        for waiter in waiters:
            waiter.set()

    def close(self) -> None:
        with self._lock:
            backends = list(self._backends.values())
        for backend in backends:
            backend.close()


# =============================================================================
# stdio loop
# =============================================================================


def _decode(raw: bytes | str) -> JsonObj | None:
    try:
        msg = json.loads(raw)
    except ValueError:
        logger.warning("acp: ignoring a line that is not JSON")
        return None
    return msg if isinstance(msg, dict) else None


def run_stdio(
    proxy_factory: Callable[[Callable[[JsonObj], None]], AcpProxy],
    client_in: IO[bytes],
    client_out: IO[bytes],
) -> None:
    """Serve one ACP client on *client_in*/*client_out* until it closes stdin."""
    write_lock = threading.Lock()

    def write_client(msg: JsonObj) -> None:
        data = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        with write_lock:
            client_out.write(data)
            client_out.flush()

    proxy = proxy_factory(write_client)
    try:
        for raw in client_in:
            if not raw.strip():
                continue
            msg = _decode(raw)
            if msg is None:
                continue
            # A session setup may start a container, so it runs on its own
            # thread and the client's other messages (cancel, answers) keep
            # flowing. Everything else is handled in order.
            if msg.get("method") in SESSION_SETUP_METHODS or msg.get("method") == "session/list":
                threading.Thread(target=proxy.handle_client, args=(msg,), daemon=True).start()
            else:
                proxy.handle_client(msg)
    finally:
        proxy.close()


def pump_backend(proxy: AcpProxy, backend: ProcessBackend) -> threading.Thread:
    """Forward the backend's stdout to the proxy on a daemon thread."""

    def run() -> None:
        for raw in backend.lines():
            if not raw.strip():
                continue
            msg = _decode(raw)
            if msg is not None:
                proxy.handle_backend(backend, msg)
        proxy.backend_exited(backend)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
