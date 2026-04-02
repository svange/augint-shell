"""ai-shell CLI entry point."""

import sys

import click

from ai_shell import __version__
from ai_shell.cli.commands.llm import llm_group
from ai_shell.cli.commands.manage import manage_group
from ai_shell.cli.commands.tools import aider, claude, claude_x, codex, opencode, shell


@click.group()
@click.version_option(version=__version__, prog_name="ai-shell")
@click.option("--project", default=None, help="Override project name for container naming.")
@click.pass_context
def cli(ctx, project):
    """AI Shell - Launch AI coding tools and local LLMs in Docker containers."""
    ctx.ensure_object(dict)
    ctx.obj["project"] = project


# Tool subcommands
cli.add_command(claude)
cli.add_command(claude_x, "claude-x")
cli.add_command(codex)
cli.add_command(opencode)
cli.add_command(aider)
cli.add_command(shell)

# Command groups
cli.add_command(llm_group, "llm")
cli.add_command(manage_group, "manage")


def main():
    """Main entry point."""
    try:
        cli()
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
