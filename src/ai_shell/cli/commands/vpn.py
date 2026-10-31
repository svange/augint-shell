"""``ai-shell vpn``: the VPN container whose proxy carries the host Chrome."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from ai_shell.cli import CONTEXT_SETTINGS
from ai_shell.config import load_config
from ai_shell.container import ContainerManager

console = Console(stderr=True)


def _manager(ctx) -> tuple[ContainerManager, object]:
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    return ContainerManager(config), config


def _echo(line: str) -> None:
    console.print(f"[dim]{line}[/dim]")


def prompt_token() -> str:
    """Ask for the NordVPN access token on the terminal (hidden)."""
    return str(
        click.prompt(
            "NordVPN access token (Nord Account, NordVPN, Manual setup; Enter to abort)",
            default="",
            hide_input=True,
            show_default=False,
        )
    )


@click.group("vpn", context_settings=CONTEXT_SETTINGS)
@click.pass_context
def vpn_group(ctx):
    """VPN container (gluetun, NordVPN) for Chrome on a host whose address sites refuse."""


@vpn_group.command("up")
@click.pass_context
def vpn_up(ctx):
    """Start the VPN container and print the address its proxy leaves from."""
    from ai_shell.vpn import VpnUnavailable, ensure_vpn_for_config

    manager, config = _manager(ctx)
    try:
        proxy = ensure_vpn_for_config(manager, config, prompt_token=prompt_token, echo=_echo)
    except VpnUnavailable as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[bold]VPN proxy ready at {proxy}.[/bold]")
    console.print(
        "[dim]Chrome uses it when claude.chrome_proxy (or AI_SHELL_CHROME_PROXY, or "
        "--chrome-proxy) is 'vpn'.[/dim]"
    )


@vpn_group.command("down")
@click.pass_context
def vpn_down(ctx):
    """Stop and remove the VPN container."""
    from ai_shell.vpn import remove_vpn

    manager, _config = _manager(ctx)
    if remove_vpn(manager):
        console.print("[bold]VPN container removed.[/bold]")
    else:
        console.print("[dim]No VPN container.[/dim]")


@vpn_group.command("status")
@click.pass_context
def vpn_status_cmd(ctx):
    """Show the VPN container state and the address its proxy leaves from."""
    from ai_shell.vpn import vpn_status

    manager, config = _manager(ctx)
    info = vpn_status(manager, config.vpn_proxy_port)
    status = info["status"] or "not created"
    console.print(f"VPN container: {status}")
    console.print(f"Proxy: {info['proxy']}")
    if info["status"] == "running":
        console.print(f"Exit address: {info['exit_address'] or 'not answering yet'}")
