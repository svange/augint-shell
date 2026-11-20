"""OpenCode on a remote box, reached over AWS Systems Manager (``ai-shell opencode remote``).

The box is an EC2 instance with ai-shell, Docker and the SSM agent, and the project in
``<projects_dir>/<project>``. Nothing on the box listens to the network: ai-shell runs the
server start through SSM Run Command and forwards the server port with an SSM port-forwarding
session. The host needs the AWS CLI v2 and the Session Manager plugin.

This module only calls the ``aws`` command; it knows nothing about Click or Docker on the host.
Its AWS CLI core (``aws``, ``ensure_login``, ``start_instance``, ``port_forward_args``) also
serves ``ai-shell ec2`` (``ec2.py``).
"""

from __future__ import annotations

import base64
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

OPENCODE_SERVER_PORT = 4096
SERVER_WAIT_SECONDS = 600  # the first start on a box pulls the dev image
LOGIN_ERRORS = (
    "Token has expired",
    "token is expired",
    "SSO session",
    "sso login",
    "The SSO session associated with this profile has expired",
    "Error loading SSO Token",
    "ExpiredToken",
)
WINDOWS_PLUGIN = Path(
    r"C:\Program Files\Amazon\SessionManagerPlugin\bin\session-manager-plugin.exe"
)
SAFE_NAME = re.compile(r"[A-Za-z0-9._-]+")


class RemoteError(Exception):
    """A step against the remote box failed; the message says what to do."""


class AwsScope(Protocol):
    """Where an AWS CLI call goes: a profile and a region (empty = the CLI's default)."""

    aws_profile: str
    aws_region: str


@dataclass
class RemoteBox:
    """The ``opencode.remote`` config block."""

    instance: str = ""  # instance id (i-...) or the value of its Name tag
    aws_profile: str = ""
    aws_region: str = ""
    user: str = "dev"  # the box user that owns the projects
    projects_dir: str = "~/projects"
    # A fixed folder under projects_dir, for a box with one server for all projects.
    # Empty: the folder named like the current folder.
    folder: str = ""
    # Runs as `user` in the project folder; {project} is the folder name.
    start_command: str = "ai-shell opencode serve"

    @classmethod
    def from_dict(cls, data: dict) -> RemoteBox:
        box = cls()
        for key in ("instance", "aws_profile", "aws_region", "user", "projects_dir", "folder"):
            if data.get(key):
                setattr(box, key, str(data[key]))
        if data.get("start_command"):
            box.start_command = str(data["start_command"])
        if not data.get("aws_profile") and data.get("profile"):
            box.aws_profile = str(data["profile"])
        if not data.get("aws_region") and data.get("region"):
            box.aws_region = str(data["region"])
        return box


def project_folder(name: str) -> str:
    """The folder name on the box; only safe characters ever reach a shell."""
    if not SAFE_NAME.fullmatch(name) or name in (".", ".."):
        raise RemoteError(f"Not a project folder name: {name!r}")
    return name


def container_slug(name: str) -> str:
    """The project name as ai-shell writes it in container names on the box."""
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9-]", "-", name.lower())).strip("-")


def find_server_port(docker_ps: str) -> int | None:
    match = re.search(rf":(\d+)->{OPENCODE_SERVER_PORT}/tcp", docker_ps)
    return int(match.group(1)) if match else None


def session_manager_plugin_found() -> bool:
    return shutil.which("session-manager-plugin") is not None or WINDOWS_PLUGIN.is_file()


def aws_env() -> dict[str, str]:
    """UTF-8 output: on Windows the AWS CLI otherwise fails on a non-cp1252 character."""
    return {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def profile_args(box: AwsScope) -> list[str]:
    args = []
    if box.aws_profile:
        args += ["--profile", box.aws_profile]
    if box.aws_region:
        args += ["--region", box.aws_region]
    return args


def aws(box: AwsScope, *cmd: str, timeout: float | None = None) -> str:
    """Run one AWS CLI command and return its stdout (always JSON output).

    stdin is closed: a profile that would prompt (an MFA code, for example) fails at once
    instead of waiting for an answer nobody sees. *timeout* bounds a credential_process
    that hangs.
    """
    if shutil.which("aws") is None:
        raise RemoteError("The AWS CLI v2 is not installed on this computer.")
    full = ["aws", *cmd, *profile_args(box), "--output", "json"]
    try:
        proc = subprocess.run(
            full,
            env=aws_env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RemoteError(f"aws {' '.join(cmd[:2])} gave no answer in {timeout:.0f} s") from exc
    if proc.returncode != 0:
        raise RemoteError(proc.stderr.strip() or proc.stdout.strip() or f"{cmd[:2]} failed")
    return proc.stdout


def ensure_login(box: AwsScope) -> None:
    """Sign in with ``aws sso login`` when the profile's session has ended."""
    try:
        aws(box, "sts", "get-caller-identity")
        return
    except RemoteError as exc:
        if not any(marker in str(exc) for marker in LOGIN_ERRORS):
            raise
    login = ["aws", "sso", "login", *(["--profile", box.aws_profile] if box.aws_profile else [])]
    if subprocess.run(login, env=aws_env(), check=False).returncode != 0:
        raise RemoteError(f"Sign-in failed. Run: {shlex.join(login)}")
    aws(box, "sts", "get-caller-identity")


def resolve_instance(box: RemoteBox) -> str:
    if not box.instance:
        raise RemoteError("No remote box: set opencode.remote.instance in ~/.augint/.ai-shell.yaml")
    if re.fullmatch(r"i-[0-9a-f]{8,17}", box.instance):
        return box.instance
    out = json.loads(
        aws(
            box,
            "ec2",
            "describe-instances",
            "--filters",
            f"Name=tag:Name,Values={box.instance}",
            "Name=instance-state-name,Values=pending,running,stopping,stopped",
        )
    )
    ids = [i["InstanceId"] for r in out.get("Reservations", []) for i in r.get("Instances", [])]
    if len(ids) != 1:
        raise RemoteError(
            f"Expected one instance named {box.instance!r}, found {len(ids)}. "
            "Set opencode.remote.instance to its instance id."
        )
    return str(ids[0])


def instance_state(box: AwsScope, instance_id: str) -> str:
    out = json.loads(aws(box, "ec2", "describe-instances", "--instance-ids", instance_id))
    return str(out["Reservations"][0]["Instances"][0]["State"]["Name"])


def ssm_online(box: AwsScope, instance_id: str) -> bool:
    out = json.loads(
        aws(
            box,
            "ssm",
            "describe-instance-information",
            "--filters",
            f"Key=InstanceIds,Values={instance_id}",
        )
    )
    info = out.get("InstanceInformationList", [])
    return bool(info) and info[0].get("PingStatus") == "Online"


def start_instance(box: AwsScope, instance_id: str, say: Callable[[str], object] = print) -> bool:
    """Start the instance when it is stopped and wait until it runs; True when it was started."""
    state = instance_state(box, instance_id)
    started = False
    if state == "stopping":
        say(f"{instance_id} is stopping; waiting before it starts again...")
        aws(box, "ec2", "wait", "instance-stopped", "--instance-ids", instance_id)
        state = "stopped"
    if state == "stopped":
        say(f"Starting {instance_id}...")
        aws(box, "ec2", "start-instances", "--instance-ids", instance_id)
        state = "pending"
        started = True
    if state == "pending":
        aws(box, "ec2", "wait", "instance-running", "--instance-ids", instance_id)
    elif state != "running":
        raise RemoteError(f"{instance_id} is {state}.")
    return started


def ensure_running(box: AwsScope, instance_id: str, say: Callable[[str], object] = print) -> None:
    """Start the box when it is stopped, and wait until SSM reaches it."""
    start_instance(box, instance_id, say=say)
    deadline = time.monotonic() + 300
    while not ssm_online(box, instance_id):
        if time.monotonic() > deadline:
            raise RemoteError("The box runs, but SSM cannot reach it yet. Try again in a minute.")
        time.sleep(5)


def run_on_box(box: RemoteBox, instance_id: str, script: str, timeout: int = 900) -> str:
    """Run *script* as root on the box through SSM Run Command and return its output."""
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    command = (
        f"echo {encoded} | base64 -d > /tmp/ai-shell-remote.sh && bash /tmp/ai-shell-remote.sh"
    )
    sent = json.loads(
        aws(
            box,
            "ssm",
            "send-command",
            "--instance-ids",
            instance_id,
            "--document-name",
            "AWS-RunShellScript",
            "--parameters",
            json.dumps({"commands": [command], "executionTimeout": [str(timeout)]}),
        )
    )
    command_id = sent["Command"]["CommandId"]
    deadline = time.monotonic() + timeout + 60
    while time.monotonic() < deadline:
        time.sleep(2)
        try:
            result = json.loads(
                aws(
                    box,
                    "ssm",
                    "get-command-invocation",
                    "--command-id",
                    command_id,
                    "--instance-id",
                    instance_id,
                )
            )
        except RemoteError as exc:
            if "InvocationDoesNotExist" in str(exc):
                continue
            raise
        status = result["Status"]
        if status in ("Pending", "InProgress", "Delayed"):
            continue
        output = str(result.get("StandardOutputContent", ""))
        if status != "Success":
            detail = f"{result.get('StandardErrorContent', '')}\n{output}".strip()
            raise RemoteError(f"{status} on the box: {detail or 'no output'}")
        return output
    raise RemoteError(f"No result from the box after {timeout} s (command {command_id}).")


def as_user(box: RemoteBox, command: str) -> str:
    """A root script that runs *command* in a login shell of the box user."""
    return f"sudo -iu {shlex.quote(box.user)} bash -lc {shlex.quote(command)}\n"


def project_dir(box: RemoteBox, project: str) -> str:
    base = box.projects_dir.rstrip("/")
    return f"{base}/{project_folder(project)}"


def server_port(box: RemoteBox, instance_id: str, project: str) -> int | None:
    slug = container_slug(project_folder(project))
    script = f"docker ps --format '{{{{.Names}}}} {{{{.Ports}}}}' | grep '^augint-shell-{slug}-' || true\n"
    return find_server_port(run_on_box(box, instance_id, script, timeout=60))


def server_answers(box: RemoteBox, instance_id: str, port: int) -> bool:
    """True when the server answers HTTP on the box (401, the password prompt, counts)."""
    probe = (
        "curl -s -o /dev/null -w '%{http_code}' --max-time 5 "
        f"http://127.0.0.1:{int(port)}/ || true\n"
    )
    code = run_on_box(box, instance_id, probe, timeout=60).strip()
    return code.isdigit() and code != "000"


def start_server(
    box: RemoteBox, instance_id: str, project: str, say: Callable[[str], object] = print
) -> int:
    """Run the start command in the project folder and wait until the server answers."""
    folder = project_dir(box, project)
    check = as_user(box, f"test -d {folder} && echo present || echo missing")
    if "present" not in run_on_box(box, instance_id, check, timeout=60):
        raise RemoteError(f"{folder} does not exist on the box. Clone the project there first.")
    command = box.start_command.replace("{project}", project_folder(project))
    say(
        f"Starting the OpenCode server for {project} on the box (the first start pulls the image)..."
    )
    run_on_box(box, instance_id, as_user(box, f"cd {folder} && {command}"))
    deadline = time.monotonic() + SERVER_WAIT_SECONDS
    while time.monotonic() < deadline:
        port = server_port(box, instance_id, project)
        if port and server_answers(box, instance_id, port):
            return port
        time.sleep(10)
    raise RemoteError(
        "The OpenCode server on the box does not answer. Its output is in "
        "/tmp/opencode-serve.log in the project's dev container on the box."
    )


def ensure_server(
    box: RemoteBox, instance_id: str, project: str, say: Callable[[str], object] = print
) -> int:
    """The server's published port, after starting the server when it does not answer."""
    port = server_port(box, instance_id, project)
    if port and server_answers(box, instance_id, port):
        return port
    return start_server(box, instance_id, project, say=say)


def server_password(box: RemoteBox, instance_id: str) -> str:
    script = as_user(box, "cat ~/.augint/opencode/server-password 2>/dev/null || true")
    return run_on_box(box, instance_id, script, timeout=60).strip()


def port_forward_args(box: AwsScope, instance_id: str, remote: int, local: int) -> list[str]:
    params = json.dumps({"portNumber": [str(remote)], "localPortNumber": [str(local)]})
    return [
        "aws",
        "ssm",
        "start-session",
        "--target",
        instance_id,
        "--document-name",
        "AWS-StartPortForwardingSession",
        "--parameters",
        params,
        *profile_args(box),
    ]
