"""Tests for ai_shell.ec2 and `ai-shell ec2`. No AWS calls; sockets and tunnels are local."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from ai_shell import ec2, remote
from ai_shell.cli.__main__ import cli
from ai_shell.ec2 import Endpoint, Instance, ProfileResult, RemoteError, Scope

SIGNED_OUT = "Error loading SSO Token: Token for corp does not exist"


def raw_instance(iid="i-0aaaaaaaaaaaaaaaa", name="web", state="running", **extra):
    data = {
        "InstanceId": iid,
        "State": {"Name": state},
        "InstanceType": "t3.micro",
        "Placement": {"AvailabilityZone": "us-east-1b"},
        "PrivateIpAddress": "10.0.0.5",
        "VpcId": "vpc-1",
        "KeyName": "main",
        "ImageId": "ami-1",
        "Tags": [{"Key": "Name", "Value": name}] if name else [],
    }
    data.update(extra)
    return data


class FakeAws:
    """Answers the AWS CLI calls ec2.py makes, per profile."""

    def __init__(self, accounts=None, ssm=None, errors=None):
        # profile -> (account, [raw instances])
        self.accounts = accounts or {"dev": ("111", [raw_instance()])}
        self.ssm = ssm if ssm is not None else {"i-0aaaaaaaaaaaaaaaa": "Online"}
        self.errors = errors or {}  # (profile, service) -> message
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.lock = threading.Lock()

    def __call__(self, scope, *cmd, timeout=None):
        with self.lock:
            self.calls.append((scope.aws_profile, cmd))
        error = self.errors.get((scope.aws_profile, cmd[0])) or self.errors.get(
            (scope.aws_profile, cmd[1] if len(cmd) > 1 else "")
        )
        if error:
            raise RemoteError(error)
        if cmd[:2] == ("configure", "list-profiles"):
            return "\n".join(self.accounts) + "\n"
        if cmd[:2] == ("ec2", "describe-instances"):
            account, instances = self.accounts[scope.aws_profile]
            if "--instance-ids" in cmd:
                wanted = cmd[cmd.index("--instance-ids") + 1]
                instances = [i for i in instances if i["InstanceId"] == wanted]
            return json.dumps({"Reservations": [{"OwnerId": account, "Instances": instances}]})
        if cmd[:2] == ("ssm", "describe-instance-information"):
            if "--filters" in cmd:
                iid = cmd[cmd.index("--filters") + 1].split("=")[-1]
                info = [{"InstanceId": iid, "PingStatus": self.ssm.get(iid, "")}]
                return json.dumps({"InstanceInformationList": info})
            info = [{"InstanceId": i, "PingStatus": s} for i, s in self.ssm.items()]
            return json.dumps({"InstanceInformationList": info})
        if cmd[:2] == ("ec2", "describe-regions"):
            return json.dumps(
                {"Regions": [{"RegionName": "us-east-1"}, {"RegionName": "eu-west-1"}]}
            )
        if cmd[:2] == ("ec2", "describe-images"):
            return json.dumps({"Images": [{"Name": "ubuntu/images/hvm-ssd/ubuntu-noble-24.04"}]})
        if cmd[:2] == ("ec2", "describe-instance-connect-endpoints"):
            return json.dumps({"InstanceConnectEndpoints": []})
        if cmd[:2] == ("ec2", "get-password-data"):
            return json.dumps({"PasswordData": "Pa55"})
        return "{}"

    def commands(self):
        return [c[:2] for _, c in self.calls]


@pytest.fixture
def fake(monkeypatch):
    aws = FakeAws()
    monkeypatch.setattr(remote, "aws", aws)
    return aws


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(ec2.time, "sleep", lambda s: None)
    monkeypatch.setattr(remote.time, "sleep", lambda s: None)


def write_config(home: Path, text: str) -> None:
    (home / ".aws").mkdir(exist_ok=True)
    (home / ".aws" / "config").write_text(text)


# --- the shared AWS CLI core ------------------------------------------------


def test_aws_closes_stdin_and_bounds_the_call(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(remote.shutil, "which", lambda name: "/usr/bin/aws")
    monkeypatch.setattr(remote.subprocess, "run", fake_run)
    with pytest.raises(RemoteError, match="no answer in 5 s"):
        remote.aws(Scope("dev"), "ec2", "describe-instances", timeout=5)
    assert seen["stdin"] is subprocess.DEVNULL


def test_start_instance_says_whether_it_started(monkeypatch):
    calls = []

    def aws(scope, *cmd, timeout=None):
        calls.append(cmd[:2])
        if cmd[:2] == ("ec2", "describe-instances"):
            return json.dumps({"Reservations": [{"Instances": [{"State": {"Name": "stopped"}}]}]})
        return "{}"

    monkeypatch.setattr(remote, "aws", aws)
    assert remote.start_instance(Scope("dev"), "i-1", say=lambda s: None) is True
    assert ("ec2", "start-instances") in calls
    assert ("ec2", "wait") in calls


def test_start_instance_leaves_a_running_instance(fake):
    assert remote.start_instance(Scope("dev"), "i-0aaaaaaaaaaaaaaaa", say=lambda s: None) is False
    assert ("ec2", "start-instances") not in fake.commands()


# --- profiles and listing ---------------------------------------------------


def test_read_aws_config_and_sign_in_commands(tmp_path, monkeypatch):
    write_config(
        Path.home(),
        "[default]\nregion = us-west-2\n"
        "[profile a]\nsso_session = corp\nregion = us-east-1\n"
        "[profile b]\nsso_session = corp\n"
        "[profile c]\nsso_start_url = https://x\n"
        "[sso-session corp]\nsso_region = us-east-1\n",
    )
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    config = ec2.read_aws_config()
    assert set(config) == {"default", "a", "b", "c"}
    assert ec2.profile_region("a", config) == "us-east-1"
    assert ec2.profile_region("b", config) == ""
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    assert ec2.profile_region("b", config) == "eu-west-1"
    results = [ProfileResult(p, "", "signed out") for p in ("a", "b", "c")]
    results.append(ProfileResult("default", "", "no access"))
    assert ec2.sign_in_commands(results, config) == [
        "aws sso login --sso-session corp",
        "aws sso login --profile c",
    ]


def test_unreadable_aws_config_is_empty(monkeypatch, tmp_path):
    bad = tmp_path / "config"
    bad.write_text("no section header\n")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(bad))
    assert ec2.read_aws_config() == {}


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (SIGNED_OUT, "signed out"),
        ("An error occurred (UnauthorizedSSOTokenError)", "signed out"),
        ("Unable to locate credentials. You can configure credentials", "no credentials"),
        ("You must specify a region. You can also configure", "no region"),
        ("An error occurred (UnauthorizedOperation) when calling", "no access"),
        ("Could not connect to the endpoint URL", "error"),
    ],
)
def test_classify(error, status):
    assert ec2.classify(error) == status


def test_parse_instances():
    data = {
        "Reservations": [
            {
                "OwnerId": "222",
                "Instances": [
                    raw_instance(),
                    raw_instance("i-0bbbbbbbbbbbbbbbb", name="", Platform="windows"),
                ],
            }
        ]
    }
    web, win = ec2.parse_instances(data, "dev", "")
    assert (web.name, web.region, web.account, web.platform) == ("web", "us-east-1", "222", "linux")
    assert web.label == "web (i-0aaaaaaaaaaaaaaaa)"
    assert web.default_port == 22
    assert win.windows and win.default_port == 3389 and win.label == "i-0bbbbbbbbbbbbbbbb"


def test_gather_lists_every_profile_and_reports_the_rest(monkeypatch):
    aws = FakeAws(
        accounts={
            "dev": ("111", [raw_instance()]),
            "dev-admin": ("111", [raw_instance()]),  # the same account through another role
            "prod": ("333", [raw_instance("i-0ccccccccccccccc0", name="db", state="stopped")]),
            "old": ("444", []),
        },
        ssm={"i-0aaaaaaaaaaaaaaaa": "Online"},
        errors={("old", "ec2"): SIGNED_OUT, ("prod", "ssm"): "AccessDeniedException"},
    )
    monkeypatch.setattr(remote, "aws", aws)
    results = ec2.gather(["dev", "dev-admin", "old", "prod"], region="us-east-1", config={})
    by_name = {r.profile: r for r in results}
    assert by_name["old"].status == "signed out"
    assert [i.instance_id for i in by_name["dev"].instances] == ["i-0aaaaaaaaaaaaaaaa"]
    assert by_name["dev-admin"].instances == []  # seen once
    (db,) = by_name["prod"].instances
    assert db.ssm == "?"  # SSM unreadable in prod
    assert by_name["dev"].instances[0].ssm == "Online"
    assert [i.name for i in ec2.all_instances(results)] == ["web", "db"]


def test_gather_all_regions(monkeypatch):
    aws = FakeAws(
        accounts={"dev": ("111", [raw_instance()]), "gone": ("9", [])},
        errors={("gone", "ec2"): "Unable to locate credentials"},
    )
    monkeypatch.setattr(remote, "aws", aws)
    results = ec2.gather(["dev", "gone"], all_regions=True, config={})
    assert {(r.profile, r.region, r.status) for r in results} == {
        ("gone", "", "no credentials"),
        ("dev", "us-east-1", "ok"),
        ("dev", "eu-west-1", "ok"),
    }
    # the same instance id answered in both regions of one account is kept once
    assert len(ec2.all_instances(results)) == 1


def test_list_scope_with_an_unreadable_answer(monkeypatch):
    monkeypatch.setattr(remote, "aws", lambda scope, *cmd, timeout=None: "not json")
    result = ec2.list_scope("dev", "us-east-1")
    assert result.status == "error" and "unreadable" in result.detail


def test_list_profiles(fake):
    fake.accounts = {"b": ("1", []), "a": ("2", [])}
    assert ec2.list_profiles() == ["a", "b"]


def test_matches_id_or_name_without_case():
    items = [Instance("i-1", name="Web"), Instance("i-2", name="db")]
    assert ec2.matches(items, "web") == items[:1]
    assert ec2.matches(items, "I-2") == items[1:]
    assert ec2.matches(items, "w") == []


def test_describe_reads_the_new_public_ip(fake):
    fake.accounts["dev"][1][0]["PublicIpAddress"] = "3.3.3.3"
    instance = Instance("i-0aaaaaaaaaaaaaaaa", profile="dev", region="us-east-1", ssm="Online")
    fresh = ec2.describe(instance)
    assert fresh.public_ip == "3.3.3.3" and fresh.ssm == "Online" and fresh.account == "111"
    with pytest.raises(RemoteError, match="gone"):
        ec2.describe(Instance("i-0nothere", profile="dev"))


# --- probes and tunnels -----------------------------------------------------


def serve_once(behaviour):
    """A local server for one or more connections; returns its port."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)

    def run():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                behaviour(conn)

    threading.Thread(target=run, daemon=True).start()
    return server, server.getsockname()[1]


def test_probe_reads_an_ssh_banner():
    server, port = serve_once(lambda c: c.sendall(b"SSH-2.0-OpenSSH_9.6\r\n"))
    with server:
        assert ec2.probe("127.0.0.1", port, expect_ssh=True) is None


def test_probe_counts_a_quiet_open_port_for_rdp():
    stop = threading.Event()
    server, port = serve_once(lambda c: stop.wait(10))
    with server:
        assert ec2.probe("127.0.0.1", port, expect_ssh=False) is None
        stop.set()


def test_probe_reasons():
    server, port = serve_once(lambda c: None)  # accepts and closes at once
    with server:
        assert "closed the connection" in ec2.probe("127.0.0.1", port, expect_ssh=True)
    server, port = serve_once(lambda c: c.sendall(b"HTTP/1.1 400\r\n"))
    with server:
        assert "not with SSH" in ec2.probe("127.0.0.1", port, expect_ssh=True)
    closed = ec2.free_port()
    assert "does not answer" in ec2.probe("127.0.0.1", closed, expect_ssh=False)


def test_free_port_and_local_port_for():
    taken = socket.socket()
    taken.bind(("127.0.0.1", 0))
    busy = taken.getsockname()[1]
    with taken:
        assert ec2.free_port(busy) != busy
    assert ec2.local_port_for(22) == 10022
    assert ec2.local_port_for(8080) == 8080


def test_start_tunnel_waits_for_the_ready_line():
    script = "import time; print('Waiting for connections...', flush=True); time.sleep(30)"
    proc = ec2.start_tunnel([sys.executable, "-c", script], ec2.SSM_READY, 1, probe_local=False)
    try:
        assert proc.poll() is None
    finally:
        proc.terminate()
        proc.wait()


def test_start_tunnel_reports_why_it_ended():
    script = "import sys; print('An error occurred (TargetNotConnected)'); sys.exit(255)"
    with pytest.raises(RemoteError, match="TargetNotConnected"):
        ec2.start_tunnel([sys.executable, "-c", script], ec2.SSM_READY, 1, probe_local=False)


def test_start_tunnel_accepts_an_open_local_port():
    server, port = serve_once(lambda c: None)
    with server:
        script = "import time; time.sleep(30)"
        proc = ec2.start_tunnel([sys.executable, "-c", script], ("never",), port, probe_local=True)
        proc.terminate()
        proc.wait()


def test_start_tunnel_gives_up(monkeypatch):
    monkeypatch.setattr(ec2, "TUNNEL_START_SECONDS", 0.5)
    script = "import time; time.sleep(30)"
    with pytest.raises(RemoteError, match="no tunnel"):
        ec2.start_tunnel([sys.executable, "-c", script], ("never",), 1, probe_local=False)


# --- transports -------------------------------------------------------------

WEB = Instance(
    "i-0aaaaaaaaaaaaaaaa",
    name="web",
    state="running",
    profile="dev",
    region="us-east-1",
    private_ip="10.0.0.5",
    vpc_id="vpc-1",
    key_name="main",
    image_id="ami-1",
    ssm="Online",
)


def test_ssm_ready_reasons(monkeypatch, fake, no_sleep):
    monkeypatch.setattr(remote, "session_manager_plugin_found", lambda: False)
    assert "plugin is not installed" in ec2.ssm_ready(WEB, False, print)
    monkeypatch.setattr(remote, "session_manager_plugin_found", lambda: True)
    assert ec2.ssm_ready(WEB, False, print) is None
    unmanaged = Instance("i-1", ssm="")
    assert "not registered with SSM" in ec2.ssm_ready(unmanaged, False, print)
    lost = Instance("i-0aaaaaaaaaaaaaaaa", profile="dev", ssm="ConnectionLost")
    fake.ssm = {"i-0aaaaaaaaaaaaaaaa": "ConnectionLost"}
    assert ec2.ssm_ready(lost, False, print) == "the SSM agent is ConnectionLost"
    said = []
    fake.ssm = {"i-0aaaaaaaaaaaaaaaa": "Online"}
    assert ec2.ssm_ready(lost, True, said.append) is None  # just started: it waits
    assert said and "Waiting for the SSM agent" in said[0]


def test_ssm_ready_tries_when_ssm_cannot_be_read(monkeypatch, no_sleep):
    monkeypatch.setattr(remote, "session_manager_plugin_found", lambda: True)

    def denied(scope, iid):
        raise RemoteError("AccessDenied")

    monkeypatch.setattr(remote, "ssm_online", denied)
    assert ec2.ssm_ready(Instance("i-1", ssm="?"), False, print) is None
    with pytest.raises(RemoteError):
        ec2.ssm_ready(Instance("i-1", ssm="ConnectionLost"), False, print)


def test_try_ssm_starts_a_port_forward(monkeypatch, fake):
    monkeypatch.setattr(remote, "session_manager_plugin_found", lambda: True)
    seen = {}

    def start(argv, ready, local, probe_local):
        seen["argv"] = argv
        return MagicMock()

    monkeypatch.setattr(ec2, "start_tunnel", start)
    endpoint = ec2.try_ssm(WEB, 22, 10022, False, print)
    assert (endpoint.method, endpoint.host, endpoint.port) == ("SSM", "127.0.0.1", 10022)
    assert "AWS-StartPortForwardingSession" in seen["argv"]
    assert seen["argv"][seen["argv"].index("--profile") + 1] == "dev"


def test_try_eice_preconditions(monkeypatch, fake):
    with pytest.raises(RemoteError, match="only ports 22 and 3389"):
        ec2.try_eice(WEB, 8080, 8080, False, print)
    with pytest.raises(RemoteError, match="in no VPC"):
        ec2.try_eice(Instance("i-1"), 22, 10022, False, print)
    with pytest.raises(RemoteError, match="no EC2 Instance Connect Endpoint in vpc-1"):
        ec2.try_eice(WEB, 22, 10022, False, print)
    fake.errors[("dev", "ec2")] = "aws: error: argument operation: Invalid choice"
    with pytest.raises(RemoteError, match="too old"):
        ec2.try_eice(WEB, 22, 10022, False, print)
    fake.errors[("dev", "ec2")] = "UnauthorizedOperation"
    with pytest.raises(RemoteError, match="cannot list endpoints"):
        ec2.try_eice(WEB, 22, 10022, False, print)


def test_try_eice_opens_and_checks_the_tunnel(monkeypatch, fake):
    def endpoints(scope, *cmd, timeout=None):
        if cmd[:2] == ("ec2", "describe-instance-connect-endpoints"):
            ready = {"InstanceConnectEndpointId": "eice-1", "State": "create-complete"}
            return json.dumps({"InstanceConnectEndpoints": [ready]})
        return fake(scope, *cmd)

    monkeypatch.setattr(remote, "aws", endpoints)
    proc = MagicMock()
    proc.poll.return_value = None
    seen = {}

    def start(argv, ready, local, probe_local):
        seen["argv"] = argv
        return proc

    monkeypatch.setattr(ec2, "start_tunnel", start)
    monkeypatch.setattr(ec2, "wait_for_port", lambda *a: None)
    endpoint = ec2.try_eice(WEB, 22, 10022, False, print)
    assert endpoint.method == "EC2 Instance Connect Endpoint eice-1"
    assert seen["argv"][:3] == ["aws", "ec2-instance-connect", "open-tunnel"]
    monkeypatch.setattr(ec2, "wait_for_port", lambda *a: "closed")
    with pytest.raises(RemoteError, match="cannot reach port 22"):
        ec2.try_eice(WEB, 22, 10022, False, print)
    proc.terminate.assert_called()


def test_try_direct_public_then_private(monkeypatch):
    tried = []

    def wait(host, port, ssh, seconds):
        tried.append((host, seconds))
        return None if host == "10.0.0.5" else f"{host}:{port} does not answer"

    monkeypatch.setattr(ec2, "wait_for_port", wait)
    instance = Instance("i-1", public_ip="3.3.3.3", private_ip="10.0.0.5")
    endpoint = ec2.try_direct(instance, 22, 0, True, print)
    assert (endpoint.method, endpoint.host, endpoint.port) == (
        "direct (private IP)",
        "10.0.0.5",
        22,
    )
    assert tried == [("3.3.3.3", ec2.PORT_WAIT_AFTER_START), ("10.0.0.5", 0)]
    with pytest.raises(RemoteError, match="no IP address"):
        ec2.try_direct(Instance("i-2"), 22, 0, False, print)


def test_wait_for_port_retries(monkeypatch, no_sleep):
    answers = iter(["refused", "refused", None])
    monkeypatch.setattr(ec2, "probe", lambda *a: next(answers))
    assert ec2.wait_for_port("h", 22, True, 60) is None
    monkeypatch.setattr(ec2, "probe", lambda *a: "refused")
    assert ec2.wait_for_port("h", 22, True, 0) == "refused"


def test_open_endpoint_tries_each_and_names_every_reason(monkeypatch):
    order = []

    def failing(name):
        def attempt(*args):
            order.append(name)
            raise RemoteError(f"{name} said no")

        return attempt

    monkeypatch.setattr(
        ec2,
        "TRANSPORTS",
        (("SSM", failing("ssm")), ("EICE", failing("eice")), ("Direct", failing("direct"))),
    )
    with pytest.raises(RemoteError) as caught:
        ec2.open_endpoint(WEB, 22, 10022, say=lambda s: None)
    assert order == ["ssm", "eice", "direct"]
    message = str(caught.value)
    assert "No way to reach port 22 on web" in message
    assert "SSM: ssm said no" in message and "Direct: direct said no" in message
    order.clear()
    with pytest.raises(RemoteError):
        ec2.open_endpoint(WEB, 22, 10022, say=lambda s: None, skip=("SSM",))
    assert order == ["eice", "direct"]


def test_open_endpoint_stops_at_the_first_that_works(monkeypatch):
    good = Endpoint("EICE", "127.0.0.1", 10022)

    def fail(*a):
        raise RemoteError("no")

    monkeypatch.setattr(
        ec2, "TRANSPORTS", (("SSM", fail), ("EICE", lambda *a: good), ("Direct", fail))
    )
    assert ec2.open_endpoint(WEB, 22, 10022, say=lambda s: None) is good


def test_endpoint_close_ends_the_process():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    Endpoint("SSM", "127.0.0.1", 1, proc).close()
    assert proc.poll() is not None
    Endpoint("direct", "h", 22).close()  # nothing to end


# --- clients ----------------------------------------------------------------


def test_login_user_from_the_image(fake):
    assert ec2.login_user(WEB) == "ubuntu"
    assert ec2.login_user(Instance("i-1", platform="windows")) == "Administrator"
    assert ec2.login_user(Instance("i-1")) == "ec2-user"
    fake.errors[("dev", "ec2")] = "InvalidAMIID.NotFound"
    assert ec2.login_user(WEB) == "ec2-user"


def test_key_file_looks_in_ssh():
    assert ec2.key_file(WEB) is None
    assert ec2.key_file(Instance("i-1")) is None
    ssh = Path.home() / ".ssh"
    ssh.mkdir()
    (ssh / "main.pem").write_text("key")
    assert ec2.key_file(WEB) == ssh / "main.pem"


@pytest.mark.skipif(not ec2.shutil.which("ssh-keygen"), reason="ssh-keygen not installed")
def test_push_temporary_key(fake, tmp_path):
    key = ec2.push_temporary_key(WEB, "ubuntu", tmp_path)
    assert key.is_file()
    (_, cmd) = fake.calls[-1]
    assert cmd[:2] == ("ec2-instance-connect", "send-ssh-public-key")
    assert cmd[cmd.index("--instance-os-user") + 1] == "ubuntu"
    assert cmd[cmd.index("--ssh-public-key") + 1].startswith("ssh-ed25519 ")


def test_push_temporary_key_needs_ssh_keygen(monkeypatch, tmp_path):
    monkeypatch.setattr(ec2.shutil, "which", lambda name: None)
    with pytest.raises(RemoteError, match="ssh-keygen"):
        ec2.push_temporary_key(WEB, "ubuntu", tmp_path)


def test_ssh_args():
    args = ec2.ssh_args(Endpoint("SSM", "127.0.0.1", 10022), "ubuntu", Path("/k"), WEB)
    assert args[:3] == ["ssh", "-p", "10022"]
    assert "HostKeyAlias=i-0aaaaaaaaaaaaaaaa" in args
    assert args[args.index("-i") + 1] == str(Path("/k"))
    assert args[-1] == "ubuntu@127.0.0.1"
    assert "-i" not in ec2.ssh_args(Endpoint("SSM", "h", 1), "u", None, WEB)


def test_windows_password(fake):
    assert ec2.windows_password(WEB, Path("/k.pem")) == "Pa55"


@pytest.mark.parametrize(
    ("platform", "found", "expected"),
    [
        ("win32", None, ["mstsc", "/v:127.0.0.1:13389"]),
        ("darwin", None, ["open", "rdp://full%20address=s:127.0.0.1:13389"]),
        ("linux", "xfreerdp", ["xfreerdp", "/v:127.0.0.1:13389"]),
        ("linux", "remmina", ["remmina", "-c", "rdp://127.0.0.1:13389"]),
        ("linux", None, None),
    ],
)
def test_rdp_client_args(monkeypatch, platform, found, expected):
    monkeypatch.setattr(ec2.sys, "platform", platform)
    monkeypatch.setattr(ec2.shutil, "which", lambda name: name if name == found else None)
    assert ec2.rdp_client_args("127.0.0.1", 13389) == expected


def test_ssm_shell_args():
    assert ec2.ssm_shell_args(WEB)[:5] == [
        "aws",
        "ssm",
        "start-session",
        "--target",
        WEB.instance_id,
    ]


# --- the CLI ----------------------------------------------------------------


@pytest.fixture
def cli_env(monkeypatch, fake):
    """Two profiles: dev (web, running) and prod (db, stopped); old is signed out."""
    fake.accounts = {
        "dev": ("111", [raw_instance(PublicIpAddress="3.3.3.3")]),
        "old": ("2", []),
        "prod": ("333", [raw_instance("i-0ccccccccccccccc0", name="db", state="stopped")]),
    }
    fake.errors[("old", "ec2")] = SIGNED_OUT
    write_config(Path.home(), "[profile old]\nsso_session = corp\n")
    return fake


def test_cli_ls(cli_env):
    result = CliRunner().invoke(cli, ["ec2", "ls"])
    assert result.exit_code == 0, result.output
    assert "web" in result.output and "db" in result.output
    assert "old: signed out" in result.output
    assert "aws sso login --sso-session corp" in result.output


def test_cli_ls_signs_in_a_named_profile(cli_env, monkeypatch):
    logins = []

    def login(scope):
        logins.append(scope.aws_profile)
        cli_env.errors.pop(("old", "ec2"))

    monkeypatch.setattr(remote, "ensure_login", login)
    result = CliRunner().invoke(cli, ["ec2", "ls", "--profile", "old"])
    assert result.exit_code == 0, result.output
    assert logins == ["old"]
    assert "No instances." in result.output


def test_cli_ls_without_profiles(fake):
    fake.accounts = {}
    result = CliRunner().invoke(cli, ["ec2", "ls"])
    assert result.exit_code == 1
    assert "No AWS profiles" in result.output


def test_cli_connect_ssh(cli_env, monkeypatch):
    endpoint = Endpoint("SSM", "127.0.0.1", 10022, MagicMock())
    endpoint.process.poll.return_value = None
    seen = {}

    def open_endpoint(instance, remote_port, local, fresh, say, skip):
        seen.update(port=remote_port, fresh=fresh, skip=skip)
        return endpoint

    monkeypatch.setattr(ec2, "open_endpoint", open_endpoint)
    monkeypatch.setattr(ec2, "push_temporary_key", lambda i, u, f: f / "id_ed25519")
    monkeypatch.setattr("ai_shell.cli.commands.ec2.shutil.which", lambda name: "/usr/bin/ssh")
    calls = []
    monkeypatch.setattr(
        "ai_shell.cli.commands.ec2.subprocess.call", lambda args, **kw: calls.append(args) or 0
    )
    result = CliRunner().invoke(cli, ["ec2", "connect", "web", "--ssh"])
    assert result.exit_code == 0, result.output
    assert seen == {"port": 22, "fresh": False, "skip": ()}
    assert calls[0][0] == "ssh" and calls[0][-1] == "ubuntu@127.0.0.1"
    assert "temporary key" in result.output
    endpoint.process.terminate.assert_called()


def test_cli_connect_starts_and_stops(cli_env, monkeypatch):
    monkeypatch.setattr(remote, "start_instance", lambda scope, iid, say: True)
    monkeypatch.setattr(
        ec2, "open_endpoint", lambda *a, **k: Endpoint("direct (public IP)", "3.3.3.3", 22)
    )
    result = CliRunner().invoke(cli, ["ec2", "connect", "db", "--stop"])
    assert result.exit_code == 0, result.output
    assert "answers on 3.3.3.3:22" in result.output
    assert ("ec2", "stop-instances") in cli_env.commands()
    # without a terminal, a started instance is not stopped unless asked
    cli_env.calls.clear()
    result = CliRunner().invoke(cli, ["ec2", "connect", "db"])
    assert result.exit_code == 0, result.output
    assert ("ec2", "stop-instances") not in cli_env.commands()


def test_cli_connect_picks_from_a_list(cli_env, monkeypatch):
    chosen = {}

    def open_endpoint(instance, *a, **k):
        chosen["id"] = instance.instance_id
        raise RemoteError("No way to reach port 22 on db")

    monkeypatch.setattr(ec2, "open_endpoint", open_endpoint)
    result = CliRunner().invoke(cli, ["ec2", "connect"], input="2\n")
    assert result.exit_code == 1
    assert chosen["id"] == "i-0ccccccccccccccc0"  # sorted by profile: dev/web, then prod/db
    assert "No way to reach port 22" in result.output


def test_cli_connect_unknown_name(cli_env):
    result = CliRunner().invoke(cli, ["ec2", "connect", "nothing"])
    assert result.exit_code == 1
    assert "No instance named 'nothing'" in result.output
    assert "old: signed out" in result.output


def test_cli_connect_tunnel_holds_until_it_ends(cli_env, monkeypatch):
    proc = MagicMock()
    proc.wait.return_value = 0
    proc.poll.return_value = 0
    seen = {}

    def open_endpoint(instance, remote_port, local, **k):
        seen.update(remote=remote_port, local=local)
        return Endpoint("SSM", "127.0.0.1", local, proc)

    monkeypatch.setattr(ec2, "open_endpoint", open_endpoint)
    result = CliRunner().invoke(cli, ["ec2", "connect", "web", "--port", "8080"])
    assert result.exit_code == 0, result.output
    assert seen["remote"] == 8080
    assert f"localhost:{seen['local']} -> web" in result.output
    proc.wait.assert_called()


def test_cli_connect_rdp(cli_env, monkeypatch):
    cli_env.accounts["dev"][1][0]["Platform"] = "windows"
    ssh = Path.home() / ".ssh"
    ssh.mkdir()
    (ssh / "main.pem").write_text("key")
    monkeypatch.setattr(
        ec2, "open_endpoint", lambda *a, **k: Endpoint("direct (public IP)", "3.3.3.3", 3389)
    )
    monkeypatch.setattr(ec2, "rdp_client_args", lambda h, p: ["mstsc", f"/v:{h}:{p}"])
    launched = []
    monkeypatch.setattr(
        "ai_shell.cli.commands.ec2.subprocess.Popen", lambda args: launched.append(args)
    )
    result = CliRunner().invoke(cli, ["ec2", "connect", "web", "--rdp"])
    assert result.exit_code == 0, result.output
    assert "Password: Pa55" in result.output
    assert launched == [["mstsc", "/v:3.3.3.3:3389"]]


def test_cli_connect_shell_over_ssm(cli_env, monkeypatch):
    monkeypatch.setattr(remote, "session_manager_plugin_found", lambda: True)
    calls = []
    monkeypatch.setattr(
        "ai_shell.cli.commands.ec2.subprocess.call", lambda args, **kw: calls.append(args) or 0
    )
    result = CliRunner().invoke(cli, ["ec2", "connect", "web", "--shell"])
    assert result.exit_code == 0, result.output
    assert calls[0][:3] == ["aws", "ssm", "start-session"]


def test_cli_connect_shell_falls_back_to_ssh(cli_env, monkeypatch):
    monkeypatch.setattr(remote, "session_manager_plugin_found", lambda: False)
    seen = {}

    def open_endpoint(instance, remote_port, local, fresh, say, skip):
        seen["skip"] = skip
        raise RemoteError("No way to reach port 22")

    monkeypatch.setattr(ec2, "open_endpoint", open_endpoint)
    result = CliRunner().invoke(cli, ["ec2", "connect", "web", "--shell"])
    assert result.exit_code == 1
    assert seen["skip"] == ("SSM",)
    assert "No SSM shell" in result.output


def test_cli_stop(cli_env):
    result = CliRunner().invoke(cli, ["ec2", "stop", "web", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Stopping web" in result.output
    assert ("ec2", "stop-instances") in cli_env.commands()


def test_cli_stop_offers_only_running_instances(cli_env):
    result = CliRunner().invoke(cli, ["ec2", "stop", "db", "--yes"])
    assert result.exit_code == 1
    assert "No instance named 'db'" in result.output
