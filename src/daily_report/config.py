"""配置装配：环境变量 → Settings。

这是密钥的唯一读取点。任何其它模块都不应直接读 os.environ。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from daily_report.errors import ConfigError

VALID_SOURCE_MODES = ("mock", "live")


def _read(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(key)
    if value is None or value.strip() == "":
        return None
    return value


def _read_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = _read(env, key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    source_mode: str = "mock"
    timezone: str = "Asia/Shanghai"
    github_token: str | None = field(default=None, repr=False)
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = field(default=None, repr=False)
    smtp_host: str | None = None
    smtp_port: int = 465
    smtp_user: str | None = None
    smtp_password: str | None = field(default=None, repr=False)
    feishu_bot_webhook: str | None = None
    max_pages: int = 10
    retry_times: int = 2


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """从环境变量装配配置。``env`` 缺省读 ``os.environ``。

    live 模式下必须提供 GitHub 令牌，否则抛 ConfigError —— 让配置错误在
    启动时暴露，而不是在采集到一半时。
    """
    source: Mapping[str, str] = os.environ if env is None else env

    source_mode = (_read(source, "DAILY_REPORT_SOURCE_MODE") or "mock").lower()
    if source_mode not in VALID_SOURCE_MODES:
        raise ConfigError(
            f"source_mode must be one of {VALID_SOURCE_MODES}, got {source_mode!r}"
        )

    github_token = _read(source, "GITHUB_TOKEN")
    if source_mode == "live" and github_token is None:
        raise ConfigError("GITHUB_TOKEN is required when source_mode=live")

    return Settings(
        source_mode=source_mode,
        timezone=_read(source, "DAILY_REPORT_TIMEZONE") or "Asia/Shanghai",
        github_token=github_token,
        feishu_app_id=_read(source, "FEISHU_APP_ID"),
        feishu_app_secret=_read(source, "FEISHU_APP_SECRET"),
        smtp_host=_read(source, "SMTP_HOST"),
        smtp_port=_read_int(source, "SMTP_PORT", 465),
        smtp_user=_read(source, "SMTP_USER"),
        smtp_password=_read(source, "SMTP_PASSWORD"),
        feishu_bot_webhook=_read(source, "FEISHU_BOT_WEBHOOK"),
        max_pages=_read_int(source, "DAILY_REPORT_MAX_PAGES", 10),
        retry_times=_read_int(source, "DAILY_REPORT_RETRY_TIMES", 2),
    )