"""ai-shell CLI entry point."""

import logging
import os
import sys

import click

from ai_shell import __version__
from ai_shell.cli import CONTEXT_SETTINGS
from ai_shell.cli.commands.llm import llm_group
from ai_shell.cli.commands.manage import manage_group
from ai_shell.cli.commands.tools import chrome, claude, codex, init, opencode, pi, shell
from ai_shell.cli.commands.vpn import vpn_group
from ai_shell.defaults import podman_cli_host


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(version=__version__, prog_name="ai-shell")
@click.option("--project", default=None, help="Override project name for container naming.")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Enable debug logging.")
@click.option(
    "--skip-updates",
    is_flag=True,
    default=False,
    help="Skip the pre-launch tool freshness check.",
)
@click.pass_context
def cli(ctx, project, verbose, skip_updates):
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


# Tool subcommands
cli.add_command(claude)
cli.add_command(chrome)
cli.add_command(codex)
cli.add_command(opencode)
cli.add_command(pi)
cli.add_command(shell)
cli.add_command(init)

# Command groups
cli.add_command(llm_group, "llm")
cli.add_command(manage_group, "manage")
cli.add_command(vpn_group, "vpn")


def main():
    """Main entry point."""
    try:
        cli()
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
