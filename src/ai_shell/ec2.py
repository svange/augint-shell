"""EC2 instances across AWS profiles (``ai-shell ec2``): list, start, connect and stop.

This module calls only the ``aws`` command, through the core in ``remote.py``, plus ``ssh``,
``ssh-keygen`` and the computer's RDP client for a session. It knows nothing about Click.

It never changes the target account to get in: no security group rule, no IAM change, no
agent install. Its only writes are start, stop and, when no key file is found, an EC2 Instance
Connect public key that the instance accepts for 60 seconds.

A connection is a *transport* (a way to reach the port) plus a *client* (ssh, an RDP client, or
nothing for a bare tunnel). The transports are tried one at a time, each only when its
preconditions hold: SSM port forwarding, an EC2 Instance Connect Endpoint tunnel, then the
instance's public and private IP. When none works, the error gives each one's reason.
"""

from __future__ import annotations

import configparser
import json
import os
import shutil
import socket
import subprocess  # nosec B404 (fixed argv lists, no shell)
import sys
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path

from ai_shell import remote as core
from ai_shell.remote import RemoteError

Say = Callable[[str], object]

LIST_TIMEOUT = 60  # one profile's listing; bounds a credential_process that hangs
LIST_WORKERS = 8
LIVE_STATES = "pending,running,stopping,stopped"
TUNNEL_START_SECONDS = 45
SSM_WAIT_AFTER_START = 180  # the agent registers a minute or two after boot
PORT_WAIT_AFTER_START = 180  # sshd or RDP after boot; Windows is slow
EICE_PORTS = (22, 3389)  # an EC2 Instance Connect Endpoint carries only these
SSM_READY = ("Waiting for connections",)
EICE_READY = ("Listening for connections",)
PLUGIN_URL = (
    "https://docs.aws.amazon.com/systems-manager/latest/userguide/"
    "session-manager-working-with-install-plugin.html"
)
SIGNED_OUT = (
    *core.LOGIN_ERRORS,
    "UnauthorizedSSOToken",
    "InvalidGrantException",
    "refresh failed",
)
NO_ACCESS = ("UnauthorizedOperation", "AccessDenied", "not authorized")
NO_REGION = ("You must specify a region",)
NO_CREDENTIALS = ("Unable to locate credentials", "Partial credentials")
# AMI name or description word -> default login user. Anything else: ec2-user.
IMAGE_USERS = (
    ("ubuntu", "ubuntu"),
    ("debian", "admin"),
    ("centos", "centos"),
    ("rocky", "rocky"),
    ("fedora", "fedora"),
    ("bitnami", "bitnami"),
    ("freebsd", "ec2-user"),
)


@dataclass
class Scope:
    """One profile in one region (empty = the AWS CLI's default)."""

    aws_profile: str = ""
    aws_region: str = ""


@dataclass
class Instance:
    instance_id: str
    name: str = ""
    state: str = ""
    instance_type: str = ""
    platform: str = "linux"  # "windows" or "linux"
    profile: str = ""
    region: str = ""
    account: str = ""
    private_ip: str = ""
    public_ip: str = ""
    vpc_id: str = ""
    key_name: str = ""
    image_id: str = ""
    # SSM PingStatus ("Online", "ConnectionLost", ...); "" = not managed; "?" = unknown
    ssm: str = "?"

    @property
    def scope(self) -> Scope:
        return Scope(self.profile, self.region)

    @property
    def windows(self) -> bool:
        return self.platform == "windows"

    @property
    def default_port(self) -> int:
        return 3389 if self.windows else 22

    @property
    def label(self) -> str:
        return f"{self.name} ({self.instance_id})" if self.name else self.instance_id


@dataclass
class ProfileResult:
    """What one profile (and region) answered."""

    profile: str
    region: str
    status: str = "ok"  # ok, signed out, no access, no region, no credentials, error
    detail: str = ""
    instances: list[Instance] = field(default_factory=list)


@dataclass
class Endpoint:
    """Where the client connects: a local tunnel, or the instance itself."""

    method: str
    host: str
    port: int
    process: subprocess.Popen | None = None

    def close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()


# --- profiles ---------------------------------------------------------------


def aws_config_path() -> Path:
    return Path(os.environ.get("AWS_CONFIG_FILE") or Path.home() / ".aws" / "config")


def read_aws_config() -> dict[str, dict[str, str]]:
    """Profile name -> its settings from the AWS config file (empty when unreadable)."""
    parser = configparser.RawConfigParser()
    try:
        parser.read(aws_config_path(), encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError):
        return {}
    profiles: dict[str, dict[str, str]] = {}
    for section in parser.sections():
        name = section[len("profile ") :] if section.startswith("profile ") else section
        if section.startswith("profile ") or section == "default":
            profiles[name.strip()] = dict(parser.items(section))
    return profiles


def list_profiles() -> list[str]:
    """Every profile the AWS CLI knows (config and credentials files)."""
    out = core.aws(Scope(), "configure", "list-profiles", timeout=LIST_TIMEOUT)
    return sorted({line.strip() for line in out.splitlines() if line.strip()})


def profile_region(profile: str, config: dict[str, dict[str, str]]) -> str:
    region = config.get(profile, {}).get("region", "")
    return region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or ""


def classify(error: str) -> str:
    for status, markers in (
        ("signed out", SIGNED_OUT),
        ("no credentials", NO_CREDENTIALS),
        ("no region", NO_REGION),
        ("no access", NO_ACCESS),
    ):
        if any(marker.lower() in error.lower() for marker in markers):
            return status
    return "error"


def first_line(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else text.strip()


def sign_in_commands(
    results: Iterable[ProfileResult], config: dict[str, dict[str, str]]
) -> list[str]:
    """One ``aws sso login`` per SSO session (or per profile) for the signed-out profiles."""
    commands: list[str] = []
    for result in results:
        if result.status != "signed out":
            continue
        session = config.get(result.profile, {}).get("sso_session", "")
        command = (
            f"aws sso login --sso-session {session}"
            if session
            else f"aws sso login --profile {result.profile}"
        )
        if command not in commands:
            commands.append(command)
    return commands


# --- listing ----------------------------------------------------------------


def _tag(tags: list[dict] | None, key: str) -> str:
    for tag in tags or []:
        if tag.get("Key") == key:
            return str(tag.get("Value", ""))
    return ""


def parse_instances(data: dict, profile: str, region: str) -> list[Instance]:
    found = []
    for reservation in data.get("Reservations", []):
        account = str(reservation.get("OwnerId", ""))
        for raw in reservation.get("Instances", []):
            platform = str(raw.get("Platform") or raw.get("PlatformDetails") or "").lower()
            zone = str(raw.get("Placement", {}).get("AvailabilityZone", ""))
            found.append(
                Instance(
                    instance_id=str(raw["InstanceId"]),
                    name=_tag(raw.get("Tags"), "Name"),
                    state=str(raw.get("State", {}).get("Name", "")),
                    instance_type=str(raw.get("InstanceType", "")),
                    platform="windows" if "windows" in platform else "linux",
                    profile=profile,
                    region=region or zone.rstrip("abcdefghijklmnopqrstuvwxyz"),
                    account=account,
                    private_ip=str(raw.get("PrivateIpAddress") or ""),
                    public_ip=str(raw.get("PublicIpAddress") or ""),
                    vpc_id=str(raw.get("VpcId") or ""),
                    key_name=str(raw.get("KeyName") or ""),
                    image_id=str(raw.get("ImageId") or ""),
                )
            )
    return found


def ssm_status(scope: Scope) -> dict[str, str] | None:
    """Instance id -> SSM PingStatus for every managed instance; None when SSM cannot be read."""
    try:
        out = json.loads(
            core.aws(scope, "ssm", "describe-instance-information", timeout=LIST_TIMEOUT)
        )
    except (RemoteError, ValueError):
        return None
    return {
        str(info.get("InstanceId")): str(info.get("PingStatus", ""))
        for info in out.get("InstanceInformationList", [])
    }


def list_scope(profile: str, region: str) -> ProfileResult:
    """The live instances of one profile in one region, with their SSM status."""
    result = ProfileResult(profile=profile, region=region)
    scope = Scope(profile, region)
    try:
        out = core.aws(
            scope,
            "ec2",
            "describe-instances",
            "--filters",
            f"Name=instance-state-name,Values={LIVE_STATES}",
            timeout=LIST_TIMEOUT,
        )
        instances = parse_instances(json.loads(out), profile, region)
    except RemoteError as exc:
        result.status, result.detail = classify(str(exc)), first_line(str(exc))
        return result
    except ValueError as exc:
        result.status, result.detail = "error", f"unreadable answer: {exc}"
        return result
    if instances:
        statuses = ssm_status(scope)
        for instance in instances:
            instance.ssm = "?" if statuses is None else statuses.get(instance.instance_id, "")
    result.instances = instances
    return result


def regions_of(profile: str, region: str) -> list[str]:
    """Every region the profile's account has enabled."""
    out = core.aws(
        Scope(profile, region or "us-east-1"),
        "ec2",
        "describe-regions",
        timeout=LIST_TIMEOUT,
    )
    return sorted(str(r["RegionName"]) for r in json.loads(out).get("Regions", []))


def gather(
    profiles: Iterable[str],
    region: str = "",
    all_regions: bool = False,
    config: dict[str, dict[str, str]] | None = None,
) -> list[ProfileResult]:
    """List every profile (and region) in parallel; an instance seen twice is kept once."""
    config = read_aws_config() if config is None else config
    names = list(profiles)
    scopes: list[tuple[str, str]] = []
    failed: list[ProfileResult] = []
    if all_regions:

        def regions_or_error(name: str) -> tuple[str, list[str] | ProfileResult]:
            home = region or profile_region(name, config)
            try:
                return name, regions_of(name, home)
            except (RemoteError, ValueError) as exc:
                return name, ProfileResult(name, home, classify(str(exc)), first_line(str(exc)))

        with ThreadPoolExecutor(max_workers=LIST_WORKERS) as pool:
            for name, answer in pool.map(regions_or_error, names):
                if isinstance(answer, ProfileResult):
                    failed.append(answer)
                else:
                    scopes += [(name, r) for r in answer]
    else:
        scopes = [(name, region or profile_region(name, config)) for name in names]
    with ThreadPoolExecutor(max_workers=LIST_WORKERS) as pool:
        results = list(pool.map(lambda s: list_scope(*s), scopes))
    seen: set[tuple[str, str]] = set()
    for result in results:
        unique = []
        for instance in result.instances:
            key = (instance.account, instance.instance_id)
            if key not in seen:
                seen.add(key)
                unique.append(instance)
        result.instances = unique
    return failed + results


def all_instances(results: Iterable[ProfileResult]) -> list[Instance]:
    found = [i for r in results for i in r.instances]
    return sorted(found, key=lambda i: (i.profile, i.region, i.name.lower(), i.instance_id))


def matches(instances: Iterable[Instance], target: str) -> list[Instance]:
    """Instances whose id or Name tag is *target* (the name without regard to case)."""
    wanted = target.strip().lower()
    return [i for i in instances if wanted in (i.instance_id.lower(), i.name.lower())]


def describe(instance: Instance) -> Instance:
    """The instance as it is now (its public IP changes when it starts)."""
    out = json.loads(
        core.aws(
            instance.scope, "ec2", "describe-instances", "--instance-ids", instance.instance_id
        )
    )
    fresh = parse_instances(out, instance.profile, instance.region)
    if not fresh:
        raise RemoteError(f"{instance.label} is gone.")
    return replace(fresh[0], ssm=instance.ssm, account=fresh[0].account or instance.account)


def start(instance: Instance) -> None:
    core.aws(instance.scope, "ec2", "start-instances", "--instance-ids", instance.instance_id)


def stop(instance: Instance) -> None:
    core.aws(instance.scope, "ec2", "stop-instances", "--instance-ids", instance.instance_id)


# --- transports -------------------------------------------------------------


def free_port(preferred: int = 0) -> int:
    """*preferred* when it is free on 127.0.0.1, else any free port."""
    for port in (preferred, 0) if preferred else (0,):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return int(sock.getsockname()[1])
    raise RemoteError("No free local port.")


def local_port_for(remote_port: int) -> int:
    """A port above 1024 that is easy to read: 22 -> 10022, 3389 -> 13389."""
    return remote_port if remote_port >= 1024 else remote_port + 10000


def probe(host: str, port: int, expect_ssh: bool, connect_timeout: float = 5.0) -> str | None:
    """None when *port* answers like a service; else why not.

    SSH speaks first, so its banner proves the whole path. Other services (RDP, HTTP) wait for
    the client: a connection that stays open counts, one that is closed at once does not.
    """
    try:
        sock = socket.create_connection((host, port), timeout=connect_timeout)
    except OSError as exc:
        return f"{host}:{port} does not answer ({exc.strerror or exc})"
    with sock:
        sock.settimeout(10 if expect_ssh else 3)
        try:
            data = sock.recv(64)
        except TimeoutError:
            return f"{host}:{port} sends no SSH banner" if expect_ssh else None
        except OSError as exc:
            return f"{host}:{port} closed the connection ({exc.strerror or exc})"
    if not data:
        return f"{host}:{port} closed the connection"
    if expect_ssh and not data.startswith(b"SSH-"):
        return f"{host}:{port} answers, but not with SSH"
    return None


def wait_for_port(host: str, port: int, expect_ssh: bool, seconds: float) -> str | None:
    """Like probe, retried for *seconds* (an instance that just started is still booting)."""
    deadline = time.monotonic() + seconds
    while True:
        reason = probe(host, port, expect_ssh)
        if reason is None or time.monotonic() >= deadline:
            return reason
        time.sleep(5)


def start_tunnel(
    argv: list[str], ready: tuple[str, ...], local_port: int, probe_local: bool
) -> subprocess.Popen:
    """Start a tunnel command and return it once it says it listens (or the port opens).

    Its output is read on a thread for the rest of its life, so the pipe never fills.
    """
    proc = subprocess.Popen(  # nosec B603 (fixed argv, no shell)
        argv,
        env=core.aws_env(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines: deque[str] = deque(maxlen=20)
    listening = threading.Event()

    def read() -> None:
        assert proc.stdout is not None  # nosec B101 (set by stdout=PIPE)
        for line in proc.stdout:
            lines.append(line.rstrip())
            if any(marker in line for marker in ready):
                listening.set()

    threading.Thread(target=read, daemon=True).start()
    deadline = time.monotonic() + TUNNEL_START_SECONDS
    while time.monotonic() < deadline:
        if listening.is_set():
            return proc
        if proc.poll() is not None:
            time.sleep(0.2)  # let the reader take the last lines
            detail = first_line("\n".join(lines)) or f"exited with code {proc.returncode}"
            raise RemoteError(detail)
        if probe_local and _listening("127.0.0.1", local_port):
            return proc
        time.sleep(0.25)
    proc.terminate()
    raise RemoteError(f"no tunnel after {TUNNEL_START_SECONDS} s")


def _listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def ssm_ready(instance: Instance, fresh: bool, say: Say) -> str | None:
    """None when SSM can carry a session to the instance; else why not."""
    if not core.session_manager_plugin_found():
        return f"the Session Manager plugin is not installed on this computer ({PLUGIN_URL})"
    if instance.ssm == "":
        return (
            "the instance is not registered with SSM (no agent, no instance profile "
            "with SSM rights, or no route to the SSM endpoints)"
        )
    if instance.ssm == "Online":
        return None
    seconds = SSM_WAIT_AFTER_START if fresh else 0
    if seconds:
        say(f"Waiting for the SSM agent on {instance.label} (up to {seconds // 60} min)...")
    deadline = time.monotonic() + seconds
    while True:
        try:
            if core.ssm_online(instance.scope, instance.instance_id):
                return None
        except RemoteError:
            if instance.ssm == "?":
                return None  # SSM status cannot be read here; let the session try
            raise
        if time.monotonic() >= deadline:
            status = instance.ssm if instance.ssm != "?" else "not Online"
            return f"the SSM agent is {status}"
        time.sleep(5)


def try_ssm(
    instance: Instance, remote_port: int, local_port: int, fresh: bool, say: Say
) -> Endpoint:
    reason = ssm_ready(instance, fresh, say)
    if reason:
        raise RemoteError(reason)
    argv = core.port_forward_args(instance.scope, instance.instance_id, remote_port, local_port)
    proc = start_tunnel(argv, SSM_READY, local_port, probe_local=False)
    return Endpoint("SSM", "127.0.0.1", local_port, proc)


def eice_endpoints(instance: Instance) -> list[str]:
    """Ready EC2 Instance Connect Endpoints in the instance's VPC."""
    try:
        out = core.aws(
            instance.scope,
            "ec2",
            "describe-instance-connect-endpoints",
            "--filters",
            f"Name=vpc-id,Values={instance.vpc_id}",
        )
    except RemoteError as exc:
        if "Invalid choice" in str(exc) or "invalid choice" in str(exc):
            raise RemoteError("this AWS CLI is too old for it (needs 2.12 or later)") from exc
        raise RemoteError(f"cannot list endpoints ({first_line(str(exc))})") from exc
    return [
        str(e.get("InstanceConnectEndpointId"))
        for e in json.loads(out).get("InstanceConnectEndpoints", [])
        if e.get("State") == "create-complete"
    ]


def try_eice(
    instance: Instance, remote_port: int, local_port: int, fresh: bool, say: Say
) -> Endpoint:
    if remote_port not in EICE_PORTS:
        raise RemoteError(f"it carries only ports 22 and 3389, not {remote_port}")
    if not instance.vpc_id:
        raise RemoteError("the instance is in no VPC")
    endpoints = eice_endpoints(instance)
    if not endpoints:
        raise RemoteError(f"there is no EC2 Instance Connect Endpoint in {instance.vpc_id}")
    argv = [
        "aws",
        "ec2-instance-connect",
        "open-tunnel",
        "--instance-id",
        instance.instance_id,
        "--instance-connect-endpoint-id",
        endpoints[0],
        "--remote-port",
        str(remote_port),
        "--local-port",
        str(local_port),
        *core.profile_args(instance.scope),
    ]
    proc = start_tunnel(argv, EICE_READY, local_port, probe_local=True)
    endpoint = Endpoint(
        f"EC2 Instance Connect Endpoint {endpoints[0]}", "127.0.0.1", local_port, proc
    )
    seconds = PORT_WAIT_AFTER_START if fresh else 0
    reason = wait_for_port("127.0.0.1", local_port, remote_port == 22, seconds)
    if reason:
        endpoint.close()
        raise RemoteError(
            f"the endpoint cannot reach port {remote_port} (a security group, a network ACL "
            "or the service on the instance)"
        )
    return endpoint


def try_direct(
    instance: Instance, remote_port: int, local_port: int, fresh: bool, say: Say
) -> Endpoint:
    addresses = [
        (k, ip)
        for k, ip in (("public", instance.public_ip), ("private", instance.private_ip))
        if ip
    ]
    if not addresses:
        raise RemoteError("the instance has no IP address")
    reasons = []
    for kind, ip in addresses:
        seconds = PORT_WAIT_AFTER_START if fresh and kind == "public" else 0
        reason = wait_for_port(ip, remote_port, remote_port == 22, seconds)
        if reason is None:
            return Endpoint(f"direct ({kind} IP)", ip, remote_port)
        reasons.append(reason)
    raise RemoteError("; ".join(reasons))


TRANSPORTS: tuple[tuple[str, Callable[[Instance, int, int, bool, Say], Endpoint]], ...] = (
    ("SSM", try_ssm),
    ("EC2 Instance Connect Endpoint", try_eice),
    ("Direct", try_direct),
)


def open_endpoint(
    instance: Instance,
    remote_port: int,
    local_port: int,
    fresh: bool = False,
    say: Say = print,
    skip: Iterable[str] = (),
) -> Endpoint:
    """The first transport that reaches *remote_port* on the instance; RemoteError when none."""
    failures = []
    for name, attempt in TRANSPORTS:
        if name in skip:
            continue
        say(f"Trying {name}...")
        try:
            return attempt(instance, remote_port, local_port, fresh, say)
        except RemoteError as exc:
            say(f"  {name}: {exc}")
            failures.append(f"{name}: {exc}")
    raise RemoteError(
        f"No way to reach port {remote_port} on {instance.label}:\n  - " + "\n  - ".join(failures)
    )


# --- clients ----------------------------------------------------------------


def login_user(instance: Instance) -> str:
    """The usual login user for the instance's image (ec2-user when the image is unknown)."""
    if instance.windows:
        return "Administrator"
    text = ""
    if instance.image_id:
        try:
            out = json.loads(
                core.aws(instance.scope, "ec2", "describe-images", "--image-ids", instance.image_id)
            )
            image = (out.get("Images") or [{}])[0]
            text = f"{image.get('Name', '')} {image.get('Description', '')}".lower()
        except (RemoteError, ValueError):
            text = ""
    for word, user in IMAGE_USERS:
        if word in text:
            return user
    return "ec2-user"


def key_file(instance: Instance) -> Path | None:
    """The instance's key pair file in ~/.ssh, when one is there."""
    if not instance.key_name:
        return None
    ssh_dir = Path.home() / ".ssh"
    for name in (instance.key_name, f"{instance.key_name}.pem"):
        if (ssh_dir / name).is_file():
            return ssh_dir / name
    return None


def push_temporary_key(instance: Instance, user: str, folder: Path) -> Path:
    """Make a key pair in *folder* and offer its public key to the instance for 60 s."""
    if shutil.which("ssh-keygen") is None:
        raise RemoteError("ssh-keygen is not installed")
    key = folder / "id_ed25519"
    made = subprocess.run(  # nosec B603 B607 (fixed argv, no shell)
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "ai-shell-ec2", "-f", str(key)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if made.returncode != 0:
        raise RemoteError(f"ssh-keygen failed: {first_line(made.stderr)}")
    public = key.with_name(key.name + ".pub").read_text(encoding="utf-8").strip()
    core.aws(
        instance.scope,
        "ec2-instance-connect",
        "send-ssh-public-key",
        "--instance-id",
        instance.instance_id,
        "--instance-os-user",
        user,
        "--ssh-public-key",
        public,
    )
    return key


def ssh_args(endpoint: Endpoint, user: str, key: Path | None, instance: Instance) -> list[str]:
    args = [
        "ssh",
        "-p",
        str(endpoint.port),
        "-o",
        f"HostKeyAlias={instance.instance_id}",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if key is not None:
        args += ["-i", str(key), "-o", "IdentitiesOnly=yes"]
    return [*args, f"{user}@{endpoint.host}"]


def windows_password(instance: Instance, key: Path) -> str:
    """The Administrator password, decrypted with the key pair file ("" when none is set)."""
    out = json.loads(
        core.aws(
            instance.scope,
            "ec2",
            "get-password-data",
            "--instance-id",
            instance.instance_id,
            "--priv-launch-key",
            str(key),
        )
    )
    return str(out.get("PasswordData") or "")


def rdp_client_args(host: str, port: int) -> list[str] | None:
    """The command that opens this computer's RDP client on host:port, or None."""
    address = f"{host}:{port}"
    if sys.platform == "win32":
        return ["mstsc", f"/v:{address}"]
    if sys.platform == "darwin":
        return ["open", f"rdp://full%20address=s:{address}"]
    for exe in ("xfreerdp3", "xfreerdp", "wlfreerdp"):
        if shutil.which(exe):
            return [exe, f"/v:{address}"]
    if shutil.which("remmina"):
        return ["remmina", "-c", f"rdp://{address}"]
    return None


def ssm_shell_args(instance: Instance) -> list[str]:
    return [
        "aws",
        "ssm",
        "start-session",
        "--target",
        instance.instance_id,
        *core.profile_args(instance.scope),
    ]


def temporary_folder() -> Path:
    return Path(tempfile.mkdtemp(prefix="ai-shell-ec2-"))
