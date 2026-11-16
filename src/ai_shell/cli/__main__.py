"""ai-shell CLI entry point."""

import logging
import os
import sys

import click

from ai_shell import __version__
from ai_shell.cli import CONTEXT_SETTINGS
from ai_shell.cli.commands.acp import acp_group
from ai_shell.cli.commands.llm import llm_group
from ai_shell.cli.commands.manage import doctor, manage_group
from ai_shell.cli.commands.tools import chrome, claude, codex, init, opencode, pi, shell
from ai_shell.cli.commands.vpn import vpn_group
from ai_shell.defaults import podman_cli_host


@click.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.version_option(version=__version__, prog_name="ai-shell")
@click.option("--project", default=None, help="Override project name for container naming.")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Enable debug logging.")
@click.option(
    "--skip-updates",
    is_flag=True,
    default=False,
    help="Skip the pre-launch tool freshness check.",
)
@click.option(
    "--agent",
    "--harness",
    "agent",
    type=click.Choice(["claude", "codex", "opencode", "pi"], case_sensitive=False),
    default=None,
    help="Launch the specified AI coding harness directly (claude, codex, opencode, pi).",
)
@click.pass_context
def cli(ctx, project, verbose, skip_updates, agent):
    """AI Shell - Launch AI coding tools and local LLMs in Docker containers."""
    ctx.ensure_object(dict)
    ctx.obj["project"] = project
    ctx.obj["skip_updates"] = skip_updates
    # Podman's CLI behind `docker` ignores DOCKER_HOST; send it to the same
    # service, or every `docker exec` fails with "OCI permission denied".
    container_host = podman_cli_host(os.environ)
    if container_host:
        os.environ["CONTAINER_HOST"] = container_host
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")

    if ctx.invoked_subcommand is None:
        if agent:
            harnesses = {
                "claude": claude,
                "codex": codex,
                "opencode": opencode,
                "pi": pi,
            }
            ctx.invoke(harnesses[agent.lower()])
        else:
            click.echo(ctx.get_help())


# Tool subcommands
cli.add_command(claude)
cli.add_command(chrome)
cli.add_command(codex)
cli.add_command(opencode)
cli.add_command(pi)
cli.add_command(shell)
cli.add_command(init)
cli.add_command(doctor)

# Command groups
cli.add_command(llm_group, "llm")
cli.add_command(manage_group, "manage")
cli.add_command(vpn_group, "vpn")
cli.add_command(acp_group, "acp")


def main():
    """Main entry point."""
    if len(sys.argv) >= 3 and sys.argv[1] == "-m" and sys.argv[2] == "ai_shell.cdp_relay":
        from ai_shell.cdp_relay import main as cdp_relay_main

        sys.exit(cdp_relay_main(sys.argv[3:]))
    try:
        cli()
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
