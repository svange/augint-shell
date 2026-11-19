"""``ai-shell ec2``: list, connect to and stop EC2 instances across AWS profiles."""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 (fixed argv lists, no shell)
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ai_shell import ec2
from ai_shell import remote as core
from ai_shell.cli import CONTEXT_SETTINGS
from ai_shell.ec2 import Instance, ProfileResult, RemoteError, Scope

out = Console()
console = Console(stderr=True)

STATE_STYLE = {"running": "green", "stopped": "dim", "pending": "yellow", "stopping": "yellow"}


def _say(line: str) -> None:
    console.print(f"[dim]{line}[/dim]", highlight=False)


def _profile_options(func):
    func = click.option(
        "--all-regions",
        is_flag=True,
        default=False,
        help="Every enabled region, not only each profile's own region.",
    )(func)
    func = click.option("--region", default="", help="Region for every profile.")(func)
    func = click.option(
        "--profile",
        "profiles",
        multiple=True,
        help="Only this AWS profile (repeatable). Default: every profile in the AWS config.",
    )(func)
    return func


def _gather(profiles: tuple[str, ...], region: str, all_regions: bool) -> list[ProfileResult]:
    """Every instance the profiles see. A named profile that is signed out signs in first."""
    try:
        names = list(profiles) or ec2.list_profiles()
    except RemoteError as exc:
        raise click.ClickException(str(exc)) from exc
    if not names:
        raise click.ClickException("No AWS profiles. Run: aws configure sso")
    config = ec2.read_aws_config()
    with console.status(f"Reading {len(names)} AWS profile(s)..."):
        results = ec2.gather(names, region, all_regions, config)
    if profiles:
        signed_out = [r for r in results if r.status == "signed out"]
        for result in signed_out:
            try:
                core.ensure_login(Scope(result.profile, result.region))
            except RemoteError as exc:
                raise click.ClickException(str(exc)) from exc
        if signed_out:
            with console.status("Reading again after sign-in..."):
                results = ec2.gather(names, region, all_regions, config)
    return results


def _problems(results: list[ProfileResult]) -> None:
    """Say which profiles gave no answer, and how to sign in to the ones that are signed out."""
    bad = [r for r in results if r.status != "ok"]
    if not bad:
        return
    console.print()
    for result in bad:
        where = f"{result.profile} ({result.region})" if result.region else result.profile
        detail = "" if result.status == "signed out" else f": {result.detail}"
        console.print(
            f"[yellow]{where}: {result.status}[/yellow][dim]{detail}[/dim]", highlight=False
        )
    commands = ec2.sign_in_commands(bad, ec2.read_aws_config())
    if commands:
        console.print("[bold]Sign in:[/bold]")
        for command in commands:
            console.print(f"  {command}", highlight=False)


def _table(instances: list[Instance], numbered: bool = False) -> Table:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    if numbered:
        table.add_column("#", justify="right")
    for column in (
        "Name",
        "Instance",
        "State",
        "Type",
        "OS",
        "SSM",
        "Public IP",
        "Private IP",
        "Profile",
        "Region",
    ):
        table.add_column(column)
    for n, instance in enumerate(instances, 1):
        style = STATE_STYLE.get(instance.state, "")
        ssm = {"": "-", "?": "?"}.get(instance.ssm, instance.ssm)
        row = [
            instance.name or "-",
            instance.instance_id,
            f"[{style}]{instance.state}[/{style}]" if style else instance.state,
            instance.instance_type,
            instance.platform,
            ssm,
            instance.public_ip or "-",
            instance.private_ip or "-",
            instance.profile,
            instance.region,
        ]
        table.add_row(*([str(n)] if numbered else []), *row)
    return table


def _choose(
    results: list[ProfileResult], target: str, states: tuple[str, ...] | None = None
) -> Instance:
    """The instance named *target*, or the one picked from a numbered table."""
    instances = ec2.all_instances(results)
    if states:
        instances = [i for i in instances if i.state in states]
    if target:
        instances = ec2.matches(instances, target)
    if not instances:
        _problems(results)
        what = f"named {target!r}" if target else "to choose from"
        raise click.ClickException(f"No instance {what}.")
    if len(instances) == 1:
        return instances[0]
    out.print(_table(instances, numbered=True))
    number: int = click.prompt(
        "Instance", type=click.IntRange(1, len(instances)), err=True, prompt_suffix=" #: "
    )
    return instances[number - 1]


@click.group("ec2", context_settings=CONTEXT_SETTINGS)
def ec2_group() -> None:
    """EC2 instances across your AWS profiles: list, connect, stop.

    Uses the AWS CLI v2 and your profiles. Connecting tries SSM, then an EC2 Instance
    Connect Endpoint, then the instance's IP, and never changes the account to get in.
    """


@ec2_group.command("ls")
@_profile_options
def ls(profiles: tuple[str, ...], region: str, all_regions: bool) -> None:
    """List the instances of every profile (or of --profile)."""
    results = _gather(profiles, region, all_regions)
    instances = ec2.all_instances(results)
    if instances:
        out.print(_table(instances))
    else:
        console.print("No instances.")
    _problems(results)


def _stop_when_done(instance: Instance, started: bool, stop_after: bool | None) -> None:
    if stop_after is None:
        stop_after = (
            started
            and sys.stdin.isatty()
            and click.confirm(f"Stop {instance.label} now?", default=True, err=True)
        )
    if stop_after:
        try:
            ec2.stop(instance)
        except RemoteError as exc:
            raise click.ClickException(str(exc)) from exc
        console.print(f"Stopping {instance.label}.")


def _hold(endpoint: ec2.Endpoint) -> int:
    """Keep the tunnel open until it ends or Ctrl+C."""
    if endpoint.process is None:
        return 0
    try:
        return endpoint.process.wait()
    except KeyboardInterrupt:
        return 0


def _ssh(instance: Instance, endpoint: ec2.Endpoint, user: str, key: Path | None) -> int:
    if shutil.which("ssh") is None:
        raise RemoteError("ssh is not installed on this computer.")
    user = user or ec2.login_user(instance)
    folder: Path | None = None
    try:
        if key is None:
            key = ec2.key_file(instance)
        if key is None:
            folder = ec2.temporary_folder()
            try:
                key = ec2.push_temporary_key(instance, user, folder)
                _say("Sent a temporary key with EC2 Instance Connect (valid for 60 s).")
            except RemoteError as exc:
                _say(
                    f"No key file and no EC2 Instance Connect key ({ec2.first_line(str(exc))}); "
                    "ssh uses your agent and default keys."
                )
        args = ec2.ssh_args(endpoint, user, key, instance)
        console.print(f"[bold]ssh {user}@{instance.label} via {endpoint.method}[/bold]")
        code = subprocess.call(args)  # nosec B603 (fixed argv, no shell)
        if code == 255:
            console.print(
                f"[yellow]ssh failed. User {user} (--user), key "
                f"{key or 'from your agent'} (--key).[/yellow]"
            )
        return code
    finally:
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)


def _rdp(instance: Instance, endpoint: ec2.Endpoint, key: Path | None, hold: bool) -> int:
    key = key or ec2.key_file(instance)
    if instance.windows and key is not None:
        try:
            password = ec2.windows_password(instance, key)
            if password:
                console.print(f"User:     Administrator\nPassword: {password}", highlight=False)
        except RemoteError as exc:
            _say(f"No Administrator password ({ec2.first_line(str(exc))}).")
    elif instance.windows and instance.key_name:
        _say(f"The Administrator password needs the key pair file: --key {instance.key_name}.pem")
    address = f"{endpoint.host}:{endpoint.port}"
    client = ec2.rdp_client_args(endpoint.host, endpoint.port)
    console.print(f"[green bold]RDP: {address} via {endpoint.method}[/green bold]")
    viewer = None
    if client is None:
        console.print("No RDP client found; open one on that address.")
    else:
        viewer = subprocess.Popen(client)  # nosec B603 (fixed argv, no shell)
    if endpoint.process is not None:
        console.print("Ctrl+C ends the tunnel.")
        return _hold(endpoint)
    if viewer is not None and hold:
        viewer.wait()  # the session ends when the RDP window closes
    return 0


def _tunnel(instance: Instance, endpoint: ec2.Endpoint, remote_port: int, hold: bool) -> int:
    if endpoint.process is None:
        console.print(
            f"[green bold]{instance.label} answers on {endpoint.host}:{endpoint.port} "
            f"({endpoint.method}); no tunnel needed.[/green bold]"
        )
        if hold and sys.stdin.isatty():
            try:
                click.prompt(
                    "Press Enter when you are done",
                    default="",
                    show_default=False,
                    err=True,
                    prompt_suffix="",
                )
            except (click.Abort, EOFError):
                pass
        return 0
    console.print(
        f"[green bold]localhost:{endpoint.port} -> {instance.label} port {remote_port} "
        f"via {endpoint.method}[/green bold]\nCtrl+C ends the tunnel."
    )
    return _hold(endpoint)


@ec2_group.command("connect")
@click.argument("target", required=False, default="")
@_profile_options
@click.option("--tunnel", "mode", flag_value="tunnel", default=True, help="A tunnel (default).")
@click.option("--ssh", "mode", flag_value="ssh", help="An SSH session.")
@click.option("--rdp", "mode", flag_value="rdp", help="Open the RDP client.")
@click.option("--shell", "mode", flag_value="shell", help="An SSM shell (no key); else --ssh.")
@click.option(
    "--port", type=int, default=0, help="Port on the instance (default 22, 3389 on Windows)."
)
@click.option("--local-port", type=int, default=0, help="Local end of the tunnel.")
@click.option("--user", default="", help="SSH user (default: from the image).")
@click.option(
    "--key",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="SSH private key or key pair file (default: ~/.ssh/<key pair name>).",
)
@click.option(
    "--stop/--no-stop",
    "stop_after",
    default=None,
    help="Stop the instance when the session ends (default: ask, when this command started it).",
)
def connect(
    target: str,
    profiles: tuple[str, ...],
    region: str,
    all_regions: bool,
    mode: str,
    port: int,
    local_port: int,
    user: str,
    key: Path | None,
    stop_after: bool | None,
) -> None:
    """Start an instance when needed and connect to it.

    TARGET is an instance id or Name tag; without it, pick from a list.
    """
    results = _gather(profiles, region, all_regions)
    instance = _choose(results, target)
    if mode == "rdp":
        remote_port = port or 3389
    elif mode in ("ssh", "shell"):
        remote_port = port or 22
    else:
        remote_port = port or instance.default_port
    started = False
    code = 0
    try:
        try:
            started = core.start_instance(instance.scope, instance.instance_id, say=_say)
            if started:
                instance = ec2.describe(instance)
            hold = stop_after is True or (stop_after is None and started)
            code = _connect(instance, mode, remote_port, local_port, user, key, started, hold)
        except RemoteError as exc:
            raise click.ClickException(str(exc)) from exc
    finally:
        _stop_when_done(instance, started, stop_after)
    if code:
        sys.exit(code)


def _connect(
    instance: Instance,
    mode: str,
    remote_port: int,
    local_port: int,
    user: str,
    key: Path | None,
    started: bool,
    hold: bool,
) -> int:
    """Open the session; *hold* keeps a session with no process of its own (direct
    tunnel, RDP) open until the user is done, because the instance is stopped after it."""
    skip: tuple[str, ...] = ()
    if mode == "shell":
        reason = ec2.ssm_ready(instance, started, _say)
        if reason is None:
            console.print(f"[bold]SSM shell on {instance.label}[/bold]")
            return subprocess.call(ec2.ssm_shell_args(instance), env=core.aws_env())  # nosec B603
        _say(f"No SSM shell: {reason}. Trying SSH.")
        mode, skip = "ssh", ("SSM",)
    if mode == "ssh":
        local = local_port or ec2.free_port()
    else:
        local = local_port or ec2.free_port(ec2.local_port_for(remote_port))
    endpoint = ec2.open_endpoint(instance, remote_port, local, fresh=started, say=_say, skip=skip)
    try:
        if mode == "ssh":
            return _ssh(instance, endpoint, user, key)
        if mode == "rdp":
            return _rdp(instance, endpoint, key, hold)
        return _tunnel(instance, endpoint, remote_port, hold)
    finally:
        endpoint.close()


@ec2_group.command("stop")
@click.argument("target", required=False, default="")
@_profile_options
@click.option("--yes", "-y", is_flag=True, default=False, help="Do not ask first.")
def stop_command(
    target: str, profiles: tuple[str, ...], region: str, all_regions: bool, yes: bool
) -> None:
    """Stop an instance. TARGET is an instance id or Name tag; without it, pick one."""
    results = _gather(profiles, region, all_regions)
    instance = _choose(results, target, states=("pending", "running"))
    if not yes:
        click.confirm(
            f"Stop {instance.label} ({instance.profile})?", default=True, abort=True, err=True
        )
    try:
        ec2.stop(instance)
    except RemoteError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"Stopping {instance.label}.")
