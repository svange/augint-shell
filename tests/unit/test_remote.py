"""Tests for ai_shell.remote and `ai-shell opencode remote`. No AWS calls."""

from __future__ import annotations

import base64
import json
import shlex
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from ai_shell import remote
from ai_shell.cli.__main__ import cli
from ai_shell.remote import RemoteBox, RemoteError

BOX = RemoteBox(instance="i-0123456789abcdef0", aws_profile="gov", aws_region="us-gov-west-1")
PS_LINE = "augint-shell-navy-1a2b3c4d-dev 0.0.0.0:24123->4096/tcp, 0.0.0.0:19000->19432/tcp"


class FakeAws:
    """Answers the AWS CLI calls the remote module makes."""

    def __init__(self, state="running", tagged=("i-0aaaaaaaaaaaaaaaa",)):
        self.calls: list[tuple[str, ...]] = []
        self.state = state
        self.tagged = list(tagged)
        self.scripts: list[str] = []

    def __call__(self, box, *cmd):
        self.calls.append(cmd)
        if cmd[:2] == ("sts", "get-caller-identity"):
            return json.dumps({"Arn": "arn:aws-us-gov:sts::1:assumed-role/x/y"})
        if cmd[:2] == ("ec2", "describe-instances"):
            if "--filters" in cmd:
                instances = [{"InstanceId": i} for i in self.tagged]
                return json.dumps({"Reservations": [{"Instances": instances}]})
            return json.dumps({"Reservations": [{"Instances": [{"State": {"Name": self.state}}]}]})
        if cmd[:2] == ("ec2", "start-instances"):
            self.state = "pending"
            return "{}"
        if cmd[:2] == ("ec2", "wait"):
            self.state = "running"
            return ""
        if cmd[:2] == ("ssm", "describe-instance-information"):
            return json.dumps({"InstanceInformationList": [{"PingStatus": "Online"}]})
        if cmd[:2] == ("ssm", "send-command"):
            params = json.loads(cmd[cmd.index("--parameters") + 1])
            encoded = params["commands"][0].split()[1]
            self.scripts.append(base64.b64decode(encoded).decode())
            return json.dumps({"Command": {"CommandId": "c-1"}})
        if cmd[:2] == ("ssm", "get-command-invocation"):
            return json.dumps({"Status": "Success", "StandardOutputContent": "ok"})
        return "{}"


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(remote.time, "sleep", lambda s: None)


def test_config_reads_the_remote_block(tmp_path):
    from ai_shell.config import load_config

    (tmp_path / ".ai-shell.yaml").write_text(
        "opencode:\n"
        "  remote:\n"
        "    instance: ai-gov-opencode-box\n"
        "    aws_profile: ai-gov\n"
        "    aws_region: us-gov-west-1\n"
        "    start_command: ai-gov-serve {project}\n"
    )
    config = load_config(project_dir=tmp_path)
    box = config.opencode_remote
    assert box.instance == "ai-gov-opencode-box"
    assert box.aws_profile == "ai-gov"
    assert box.aws_region == "us-gov-west-1"
    assert box.user == "dev"
    assert box.projects_dir == "~/projects"
    assert box.start_command == "ai-gov-serve {project}"


def test_default_config_has_no_remote_box(tmp_path):
    from ai_shell.config import load_config

    assert load_config(project_dir=tmp_path).opencode_remote == RemoteBox()


@pytest.mark.parametrize("name", ["..", "a b", "x;rm", "a/b", ""])
def test_project_folder_rejects_unsafe_names(name):
    with pytest.raises(RemoteError):
        remote.project_folder(name)


def test_find_server_port():
    assert remote.find_server_port(PS_LINE) == 24123
    assert remote.find_server_port("") is None


def test_aws_asks_for_json_and_utf8(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen.update(kwargs)
        return MagicMock(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(remote.shutil, "which", lambda name: "/usr/bin/aws")
    monkeypatch.setattr(remote.subprocess, "run", fake_run)
    remote.aws(BOX, "sts", "get-caller-identity")
    cmd = seen["cmd"]
    assert cmd[cmd.index("--output") + 1] == "json"
    assert cmd[cmd.index("--profile") + 1] == "gov"
    assert cmd[cmd.index("--region") + 1] == "us-gov-west-1"
    assert seen["env"]["PYTHONUTF8"] == "1"


def test_expired_sign_in_runs_sso_login(monkeypatch):
    answers = iter([RemoteError("Error loading SSO Token: Token has expired"), "{}"])

    def aws(box, *cmd):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    logins = []
    monkeypatch.setattr(remote, "aws", aws)
    monkeypatch.setattr(
        remote.subprocess, "run", lambda cmd, **kw: logins.append(cmd) or MagicMock(returncode=0)
    )
    remote.ensure_login(BOX)
    assert logins == [["aws", "sso", "login", "--profile", "gov"]]


def test_resolve_instance_by_name_tag(monkeypatch):
    monkeypatch.setattr(remote, "aws", FakeAws())
    box = RemoteBox(instance="ai-gov-opencode-box")
    assert remote.resolve_instance(box) == "i-0aaaaaaaaaaaaaaaa"


def test_resolve_instance_needs_exactly_one(monkeypatch):
    monkeypatch.setattr(remote, "aws", FakeAws(tagged=()))
    with pytest.raises(RemoteError, match="found 0"):
        remote.resolve_instance(RemoteBox(instance="nothing"))
    with pytest.raises(RemoteError, match="opencode.remote.instance"):
        remote.resolve_instance(RemoteBox())


def test_ensure_running_starts_a_stopped_box_and_waits_for_ssm(monkeypatch, no_sleep):
    fake = FakeAws(state="stopped")
    monkeypatch.setattr(remote, "aws", fake)
    remote.ensure_running(BOX, BOX.instance, say=lambda s: None)
    names = [c[:2] for c in fake.calls]
    assert ("ec2", "start-instances") in names
    assert names.index(("ec2", "wait")) < names.index(("ssm", "describe-instance-information"))


def test_run_on_box_sends_the_script(monkeypatch, no_sleep):
    fake = FakeAws()
    monkeypatch.setattr(remote, "aws", fake)
    assert remote.run_on_box(BOX, BOX.instance, "echo it's\n") == "ok"
    assert fake.scripts == ["echo it's\n"]


def test_a_failed_command_shows_its_output(monkeypatch, no_sleep):
    fake = FakeAws()

    def aws(box, *cmd):
        if cmd[:2] == ("ssm", "get-command-invocation"):
            return json.dumps(
                {
                    "Status": "Failed",
                    "StandardOutputContent": "",
                    "StandardErrorContent": "opencode serve exited at start",
                }
            )
        return fake(box, *cmd)

    monkeypatch.setattr(remote, "aws", aws)
    with pytest.raises(RemoteError, match="opencode serve exited at start"):
        remote.run_on_box(BOX, BOX.instance, "true\n")


def test_as_user_quotes_the_command():
    argv = shlex.split(remote.as_user(BOX, "cd ~/projects/navy && echo it's"))
    assert argv[:4] == ["sudo", "-iu", "dev", "bash"]
    assert argv[-1] == "cd ~/projects/navy && echo it's"


def fake_box(monkeypatch, answer):
    scripts: list[str] = []

    def run_on_box(box, instance_id, script, timeout=900):
        scripts.append(script)
        return answer(script)

    monkeypatch.setattr(remote, "run_on_box", run_on_box)
    return scripts


def test_ensure_server_reuses_a_server_that_answers(monkeypatch, no_sleep):
    scripts = fake_box(monkeypatch, lambda s: PS_LINE if s.startswith("docker ps") else "401")
    assert remote.ensure_server(BOX, BOX.instance, "navy", say=lambda s: None) == 24123
    assert not any("ai-shell opencode serve" in s for s in scripts)


def test_ensure_server_starts_a_silent_server(monkeypatch, no_sleep):
    answers = iter(["000", "401"])

    def answer(script):
        if script.startswith("docker ps"):
            return PS_LINE
        if script.startswith("curl "):
            return next(answers)
        if "test -d" in script:
            return "present\n"
        return ""

    scripts = fake_box(monkeypatch, answer)
    box = RemoteBox(instance=BOX.instance, start_command="ai-gov-serve {project}")
    assert remote.ensure_server(box, box.instance, "navy", say=lambda s: None) == 24123
    started = [s for s in scripts if "ai-gov-serve" in s]
    assert len(started) == 1
    assert shlex.split(started[0])[-1] == "cd ~/projects/navy && ai-gov-serve navy"


def test_start_server_needs_the_project_on_the_box(monkeypatch, no_sleep):
    fake_box(monkeypatch, lambda s: "missing\n" if "test -d" in s else "")
    with pytest.raises(RemoteError, match="~/projects/navy does not exist"):
        remote.start_server(BOX, BOX.instance, "navy", say=lambda s: None)


def test_port_forward_args():
    args = remote.port_forward_args(BOX, BOX.instance, 24123, 5000)
    params = json.loads(args[args.index("--parameters") + 1])
    assert params == {"portNumber": ["24123"], "localPortNumber": ["5000"]}
    assert args[args.index("--profile") + 1] == "gov"


def test_cli_remote_opens_the_tunnel(monkeypatch, tmp_path):
    (tmp_path / ".ai-shell.yaml").write_text(
        "opencode:\n  remote:\n    instance: i-0123456789abcdef0\n    aws_profile: gov\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(remote, "session_manager_plugin_found", lambda: True)
    monkeypatch.setattr(remote, "ensure_login", lambda box: None)
    monkeypatch.setattr(remote, "ensure_running", lambda box, i, say=print: None)
    monkeypatch.setattr(remote, "ensure_server", lambda box, i, p, say=print: 24123)
    monkeypatch.setattr(remote, "server_password", lambda box, i: "s3cret")
    started = {}

    class FakePopen:
        def __init__(self, cmd, env=None):
            started["cmd"] = cmd

        def poll(self):
            return None

        def wait(self):
            return 0

    with (
        patch("ai_shell.cli.commands.tools.subprocess.Popen", FakePopen),
        patch("ai_shell.cli.commands.tools.webbrowser.open") as browser,
        patch("time.sleep"),
    ):
        result = CliRunner().invoke(cli, ["opencode", "remote", "navy"])

    assert result.exit_code == 0, result.output
    assert "OpenCode for navy: http://localhost:24123" in result.output
    assert "Password: s3cret" in result.output
    assert started["cmd"][:4] == ["aws", "ssm", "start-session", "--target"]
    browser.assert_called_once_with("http://localhost:24123")


def test_cli_remote_without_a_box_says_how_to_set_one(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(remote, "session_manager_plugin_found", lambda: True)
    monkeypatch.setattr(remote, "ensure_login", lambda box: None)
    result = CliRunner().invoke(cli, ["opencode", "remote"])
    assert result.exit_code == 1
    assert "opencode.remote.instance" in result.output


def test_project_defaults_to_this_folder_name(monkeypatch, tmp_path):
    folder = tmp_path / "navy"
    folder.mkdir()
    monkeypatch.chdir(folder)
    seen = {}
    monkeypatch.setattr(remote, "session_manager_plugin_found", lambda: True)
    monkeypatch.setattr(remote, "ensure_login", lambda box: None)
    monkeypatch.setattr(remote, "resolve_instance", lambda box: "i-1")
    monkeypatch.setattr(remote, "ensure_running", lambda box, i, say=print: None)

    def ensure_server(box, i, project, say=print):
        seen["project"] = project
        raise RemoteError("stop here")

    monkeypatch.setattr(remote, "ensure_server", ensure_server)
    result = CliRunner().invoke(cli, ["opencode", "remote"])
    assert result.exit_code == 1
    assert seen["project"] == Path.cwd().name == "navy"
