"""``ai-shell acp``: serve an ACP client (JetBrains Air, Zed) from the dev container.

The client starts ``ai-shell acp <tool>`` as its agent command. The proxy in
:mod:`ai_shell.acp` runs the tool's ACP adapter in each project's dev container
and maps the project's paths between host and container. This module only
builds the adapter command, the environment and the extra MCP servers for one
project, from the same helpers ``ai-shell claude`` uses.

stdout belongs to the protocol. The command moves the process's own stdout to
stderr before anything runs, so no ai-shell message can corrupt the stream.
"""

from __future__ import annotations

import logging
import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

import click

from ai_shell.cli import CONTEXT_SETTINGS
from ai_shell.config import AiShellConfig, load_config

logger = logging.getLogger(__name__)

CLAUDE_EXECUTABLE = "/root/.local/bin/claude"


@dataclass(frozen=True)
class Adapter:
    """How to start one tool's ACP adapter in the container."""

    binary: str
    args: tuple[str, ...] = ()
    npm_package: str | None = None  # installed on demand on images that lack it

    def shell_command(self) -> list[str]:
        """``sh -c`` that installs the adapter when missing, then runs it."""
        run = shlex.join([self.binary, *self.args])
        if self.npm_package is None:
            return ["sh", "-c", f"exec {run}"]
        install = (
            f"command -v {shlex.quote(self.binary)} >/dev/null 2>&1 || "
            f"npm install -g {shlex.quote(self.npm_package)} >&2"
        )
        return ["sh", "-c", f"{install}; exec {run}"]


ADAPTERS: dict[str, Adapter] = {
    "claude": Adapter("claude-agent-acp", npm_package="@agentclientprotocol/claude-agent-acp"),
    "codex": Adapter("codex-acp", npm_package="@agentclientprotocol/codex-acp"),
    "opencode": Adapter("opencode", ("acp",)),
}


def container_project_root(config: AiShellConfig) -> str:
    """Where ``build_dev_mounts`` mounts the project in the dev container."""
    return f"/root/projects/{config.project_name}"


def folder_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


# =============================================================================
# Per-project backend
# =============================================================================


@dataclass(frozen=True)
class AcpOptions:
    tool: str
    account: str | None = None
    local_chrome: bool | None = None  # None: as configured for the account
    skip_updates: bool = False


def _tool_env(config: AiShellConfig, opts: AcpOptions) -> tuple[dict[str, str], list[str], str]:
    """Return (exec env, command prefix, resolved Claude account) for one project."""
    from ai_shell.defaults import build_dev_environment

    if opts.tool != "claude":
        env = build_dev_environment(
            config.extra_env,
            config.project_dir,
            project_name=config.project_name,
            aws_profile=config.ai_profile,
            aws_region=config.aws_region,
            openai_profile=config.openai_profile,
        )
        return env, [], ""

    from ai_shell.cli.commands.tools import _claude_account_cmd_prefix, _claude_exec_env
    from ai_shell.defaults import CLAUDE_CONFIG_DIR_VAR

    account = opts.account or config.claude_account
    env = _claude_exec_env(
        config,
        use_bedrock=config.claude_provider == "aws",
        cli_profile=None,
        claude_account=account,
        env_file=None,
    )
    env = dict(env)
    # The adapter runs the image's Claude Code, the one `ai-shell claude` keeps current.
    env["CLAUDE_CODE_EXECUTABLE"] = CLAUDE_EXECUTABLE
    if CLAUDE_CONFIG_DIR_VAR in env:
        logger.info(
            "Account '%s' uses its login profile. If it is not signed in, run "
            "'ai-shell claude --account %s' once in a terminal.",
            account,
            account,
        )
    return env, _claude_account_cmd_prefix(env), account


def _chrome_mcp_servers(
    manager, container_name: str, config: AiShellConfig, opts: AcpOptions, account: str
) -> list[dict]:
    """The Chrome DevTools MCP for this project, when local Chrome is on."""
    from ai_shell.cli.commands.tools import (
        _account_chrome_profile,
        _account_chrome_proxy,
        _configure_local_chrome,
        _resolve_local_chrome,
    )

    if opts.tool != "claude" or opts.local_chrome is False:
        return []
    if not _resolve_local_chrome(config, account, bool(opts.local_chrome)):
        return []

    from ai_shell.acp import stdio_mcp_server
    from ai_shell.local_chrome import CHROME_MCP_SERVER_NAME, chrome_mcp_server_spec
    from ai_shell.vpn import VPN_PROXY_SENTINEL, ensure_vpn_for_config

    proxy = _account_chrome_proxy(config, account)
    if proxy and proxy.lower() == VPN_PROXY_SENTINEL:
        # No prompt: stdin is the protocol. A missing token fails with its reason.
        proxy = ensure_vpn_for_config(
            manager, config, prompt_token=None, echo=lambda line: logger.info("%s", line)
        )
    _, _, port = _configure_local_chrome(
        container_name,
        project_name=config.project_name,
        project_dir=config.project_dir,
        chrome_profile=_account_chrome_profile(config, account),
        chrome_proxy=proxy,
    )
    return [stdio_mcp_server(CHROME_MCP_SERVER_NAME, chrome_mcp_server_spec(port))]


def start_backend(cwd: str, opts: AcpOptions):
    """Start the adapter in the dev container of the project at *cwd*."""
    from ai_shell.acp import PathMap, ProcessBackend
    from ai_shell.container import ContainerManager

    project_dir = Path(cwd)
    if not project_dir.is_dir():
        raise ValueError(f"{cwd} is not a folder on this machine")
    config = load_config(project_dir=project_dir)
    if opts.skip_updates:
        config.skip_updates = True
    manager = ContainerManager(config)
    container_name = manager.ensure_dev_container()
    env, prefix, account = _tool_env(config, opts)
    mcp_servers = _chrome_mcp_servers(manager, container_name, config, opts, account)
    root = container_project_root(config)
    argv = manager.exec_args(
        container_name,
        [*prefix, *ADAPTERS[opts.tool].shell_command()],
        extra_env=env,
        workdir=root,
        stdin=True,
    )
    logger.info("Starting %s in %s for %s", opts.tool, container_name, project_dir)
    return ProcessBackend(
        container_name,
        PathMap(str(project_dir.resolve()), root),
        argv,
        mcp_servers,
    )


def probe_argv(image: str, tool: str) -> list[str]:
    """``docker run`` of the adapter in the image, with no project, to answer ``initialize``."""
    return [
        "docker",
        "run",
        "--rm",
        "-i",
        "--entrypoint",
        "",
        "-e",
        f"CLAUDE_CODE_EXECUTABLE={CLAUDE_EXECUTABLE}",
        image,
        *ADAPTERS[tool].shell_command(),
    ]


# =============================================================================
# Command
# =============================================================================


def serve(opts: AcpOptions) -> None:
    """Run the proxy on this process's stdio until the client closes it."""
    from ai_shell.acp import AcpProxy, probe_initialize, pump_backend, run_stdio

    client_in = sys.stdin.buffer
    client_out = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    # From here on fd 1 is stderr, for this process and every child it starts.
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr

    image = load_config(project_dir=Path.cwd()).full_image

    def make_proxy(write_client):
        holder: dict[str, AcpProxy] = {}

        def factory(cwd: str):
            backend = start_backend(cwd, opts)
            pump_backend(holder["proxy"], backend)
            return backend

        proxy = AcpProxy(
            write_client=write_client,
            backend_factory=factory,
            probe=lambda params: probe_initialize(probe_argv(image, opts.tool), params),
            folder_key=folder_key,
        )
        holder["proxy"] = proxy
        return proxy

    run_stdio(make_proxy, client_in, client_out)


@click.group("acp", context_settings=CONTEXT_SETTINGS)
def acp_group():
    """Serve an ACP client (JetBrains Air, Zed) from the dev container.

    Register the command as a custom agent in the client, for example in
    ~/.jetbrains/acp.json. The project comes from each session, so one entry
    serves every project. See the README section "ACP clients".
    """


def _setup_logging(ctx: click.Context) -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="ai-shell: %(message)s")


@acp_group.command("claude", context_settings=CONTEXT_SETTINGS)
@click.option(
    "--account",
    "cli_account",
    default=None,
    help="Claude account, as for `ai-shell claude --account`.",
)
@click.option(
    "--local-chrome/--no-local-chrome",
    "local_chrome",
    default=None,
    help="Attach the host Chrome (DevTools MCP). Default: as configured for the account.",
)
@click.pass_context
def acp_claude(ctx, cli_account, local_chrome):
    """Claude Code (claude-agent-acp) in the dev container."""
    _setup_logging(ctx)
    serve(
        AcpOptions(
            tool="claude",
            account=cli_account,
            local_chrome=local_chrome,
            skip_updates=bool(ctx.obj and ctx.obj.get("skip_updates")),
        )
    )


@acp_group.command("codex", context_settings=CONTEXT_SETTINGS)
@click.pass_context
def acp_codex(ctx):
    """Codex (codex-acp) in the dev container."""
    _setup_logging(ctx)
    serve(AcpOptions(tool="codex", skip_updates=bool(ctx.obj and ctx.obj.get("skip_updates"))))


@acp_group.command("opencode", context_settings=CONTEXT_SETTINGS)
@click.pass_context
def acp_opencode(ctx):
    """OpenCode (opencode acp) in the dev container."""
    _setup_logging(ctx)
    serve(AcpOptions(tool="opencode", skip_updates=bool(ctx.obj and ctx.obj.get("skip_updates"))))
