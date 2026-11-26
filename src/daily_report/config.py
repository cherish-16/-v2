"""配置装配：环境变量 → Settings。

这是密钥的唯一读取点。任何其它模块都不应直接读 os.environ。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    github_owner: str = ""
    insecure_tls: bool = False
    github_repo: str = ""
    github_branch: str | None = None
    attendance_position: str = "end"


def _env_file_values(path: str = ".env") -> dict[str, str]:
    """读取 .env 文件（KEY=VALUE 格式，忽略注释与空行）。

    这不是完整的 dotenv 实现，只覆盖本项目需要的子集：
    不做变量展开、不处理引号包裹的多行值。
    """
    target = Path(path)
    if not target.exists():
        return {}
    values: dict[str, str] = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def load_settings(
    env: Mapping[str, str] | None = None, *, env_file: str | None = ".env"
) -> Settings:
    """从环境变量装配配置。

    优先级：显式传入的 ``env`` > 进程环境变量 > ``.env`` 文件。
    显式传 ``env``（测试常用）时完全不读 ``.env``，保证测试可隔离。
    """
    if env is not None:
        source: Mapping[str, str] = env
    else:
        merged: dict[str, str] = {}
        if env_file:
            merged.update(_env_file_values(env_file))
        merged.update(os.environ)  # 进程环境变量优先于文件
        source = merged

    source_mode = (_read(source, "DAILY_REPORT_SOURCE_MODE") or "mock").lower()
    if source_mode not in VALID_SOURCE_MODES:
        raise ConfigError(
            f"source_mode must be one of {VALID_SOURCE_MODES}, got {source_mode!r}"
        )

    github_token = _read(source, "GITHUB_TOKEN")
    if source_mode == "live" and github_token is None:
        raise ConfigError("GITHUB_TOKEN is required when source_mode=live")

    tz_name = _read(source, "DAILY_REPORT_TIMEZONE") or "Asia/Shanghai"
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        # 拼错的时区会让整天的采集窗口平移，必须在启动时暴露而不是回退 UTC。
        raise ConfigError(
            f"invalid DAILY_REPORT_TIMEZONE: {tz_name!r} ({exc})"
        ) from exc

    return Settings(
        source_mode=source_mode,
        timezone=tz_name,
        github_token=github_token,
        feishu_app_id=_read(source, "FEISHU_APP_ID"),
        feishu_app_secret=_read(source, "FEISHU_APP_SECRET"),
        smtp_host=_read(source, "SMTP_HOST"),
        smtp_port=_read_int(source, "SMTP_PORT", 465),
        smtp_user=_read(source, "SMTP_USER"),
        smtp_password=_read(source, "SMTP_PASSWORD"),
        feishu_bot_webhook=_read(source, "FEISHU_BOT_WEBHOOK"),
        github_owner=_read(source, "GITHUB_OWNER") or "",
        insecure_tls=(_read(source, "DAILY_REPORT_INSECURE_TLS") or "").lower()
        in ("1", "true", "yes"),
        github_repo=_read(source, "GITHUB_REPO") or "",
        github_branch=_read(source, "GITHUB_BRANCH"),
        max_pages=_read_int(source, "DAILY_REPORT_MAX_PAGES", 10),
        retry_times=_read_int(source, "DAILY_REPORT_RETRY_TIMES", 2),
    )