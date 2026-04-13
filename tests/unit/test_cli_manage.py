"""Tests for CLI manage subcommands."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from ai_shell.cli.__main__ import cli

LEGACY_NAME = "augint-shell-myproj-dev"


@patch("ai_shell.cli.commands.manage.ContainerManager")
@patch("ai_shell.cli.commands.manage.load_config")
class TestManageResolvesLegacyNames:
    """Verify status/stop/clean/logs use resolve_dev_container() for name lookup."""

    def setup_method(self):
        self.runner = CliRunner()

    def _setup_manager(self, mock_cm_class):
        manager = MagicMock()
        mock_cm_class.return_value = manager
        manager.resolve_dev_container.return_value = (LEGACY_NAME, MagicMock())
        manager.config.project_name = "myproj"
        return manager

    def test_clean_finds_legacy_container(self, _mock_config, mock_cm_class):
        manager = self._setup_manager(mock_cm_class)
        result = self.runner.invoke(cli, ["manage", "clean"])
        assert result.exit_code == 0
        manager.remove_container.assert_called_once_with(LEGACY_NAME)

    def test_stop_finds_legacy_container(self, _mock_config, mock_cm_class):
        manager = self._setup_manager(mock_cm_class)
        result = self.runner.invoke(cli, ["manage", "stop"])
        assert result.exit_code == 0
        manager.stop_container.assert_called_once_with(LEGACY_NAME)

    def test_status_finds_legacy_container(self, _mock_config, mock_cm_class):
        manager = self._setup_manager(mock_cm_class)
        manager.container_status.return_value = "running"
        manager.container_ports.return_value = {}
        result = self.runner.invoke(cli, ["manage", "status"])
        assert result.exit_code == 0
        manager.container_status.assert_called_once_with(LEGACY_NAME)
        assert LEGACY_NAME in result.output

    def test_logs_finds_legacy_container(self, _mock_config, mock_cm_class):
        manager = self._setup_manager(mock_cm_class)
        result = self.runner.invoke(cli, ["manage", "logs"])
        assert result.exit_code == 0
        manager.container_logs.assert_called_once_with(LEGACY_NAME, follow=False)


@patch("ai_shell.cli.commands.manage.load_config")
class TestManageEnv:
    def setup_method(self):
        self.runner = CliRunner()

    def test_manage_env_shows_variables(self, mock_config, tmp_path):
        config = MagicMock()
        config.claude_provider = ""
        config.extra_env = {}
        config.project_dir = tmp_path
        config.ai_profile = ""
        config.aws_region = ""
        config.bedrock_profile = ""
        mock_config.return_value = config

        result = self.runner.invoke(cli, ["manage", "env"])

        assert result.exit_code == 0
        assert "AWS_REGION" in result.output
        assert "IS_SANDBOX" in result.output
        assert "CLAUDE_CODE_USE_BEDROCK" not in result.output

    def test_manage_env_with_aws_flag(self, mock_config, tmp_path):
        config = MagicMock()
        config.claude_provider = ""
        config.extra_env = {}
        config.project_dir = tmp_path
        config.ai_profile = ""
        config.aws_region = ""
        config.bedrock_profile = "rd"
        mock_config.return_value = config

        result = self.runner.invoke(cli, ["manage", "env", "--aws"])

        assert result.exit_code == 0
        assert "CLAUDE_CODE_USE_BEDROCK=1" in result.output
        assert "AWS_PROFILE=rd" in result.output

    def test_manage_env_config_provider_activates_bedrock(self, mock_config, tmp_path):
        config = MagicMock()
        config.claude_provider = "aws"
        config.extra_env = {}
        config.project_dir = tmp_path
        config.ai_profile = ""
        config.aws_region = ""
        config.bedrock_profile = "rd"
        mock_config.return_value = config

        result = self.runner.invoke(cli, ["manage", "env"])

        assert result.exit_code == 0
        assert "CLAUDE_CODE_USE_BEDROCK=1" in result.output

    def test_manage_env_masks_tokens(self, mock_config, tmp_path):
        config = MagicMock()
        config.claude_provider = ""
        config.extra_env = {}
        config.project_dir = tmp_path
        config.ai_profile = ""
        config.aws_region = ""
        config.bedrock_profile = ""
        mock_config.return_value = config

        with patch.dict("os.environ", {"GH_TOKEN": "ghp_abcdefghijklmnop"}):
            result = self.runner.invoke(cli, ["manage", "env"])

        assert "ghp_abcdefghijklmnop" not in result.output
        assert "ghp_" in result.output
        assert "...mnop" in result.output
