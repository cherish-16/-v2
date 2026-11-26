import pytest

from daily_report.config import load_settings
from daily_report.errors import ConfigError


def test_defaults_to_mock_mode():
    settings = load_settings({})
    assert settings.source_mode == "mock"
    assert settings.max_pages == 10
    assert settings.retry_times == 2


def test_live_mode_requires_github_token():
    with pytest.raises(ConfigError, match="GITHUB_TOKEN"):
        load_settings({"DAILY_REPORT_SOURCE_MODE": "live"})


def test_live_mode_accepts_complete_config():
    settings = load_settings(
        {
            "DAILY_REPORT_SOURCE_MODE": "live",
            "GITHUB_TOKEN": "t0ken",
            "FEISHU_APP_ID": "cli_x",
            "FEISHU_APP_SECRET": "secret",
        }
    )
    assert settings.source_mode == "live"
    assert settings.github_token == "t0ken"


def test_invalid_source_mode_rejected():
    with pytest.raises(ConfigError, match="source_mode"):
        load_settings({"DAILY_REPORT_SOURCE_MODE": "staging"})


def test_settings_repr_does_not_leak_secrets():
    settings = load_settings({"GITHUB_TOKEN": "super-secret-value"})
    assert "super-secret-value" not in repr(settings)