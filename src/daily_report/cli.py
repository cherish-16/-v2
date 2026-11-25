"""命令行入口。

退出码：0 成功或重复触发；2 参数错误。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

import httpx

from daily_report.collectors.base import SourceBundle
from daily_report.collectors.feishu import FeishuMessageSource, FeishuTaskSource
from daily_report.collectors.github import GitHubCommitSource
from daily_report.collectors.mock import MockSourceBundle
from daily_report.config import Settings, load_settings
from daily_report.errors import ReportError
from daily_report.orchestration.run_daily import PublisherBundle, run_daily
from daily_report.publishers.email import SmtpEmailPublisher
from daily_report.publishers.feishu_bot import WebhookBotPublisher
from daily_report.storage.repository import Repository
from daily_report.storage.schema import init_db


def _parse_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date: {raw!r}") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="daily_report")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="生成并推送指定日期的日报")
    run.add_argument("--team", required=True, help="团队标识")
    run.add_argument("--date", type=_parse_date, default=date.today(), help="YYYY-MM-DD")
    run.add_argument("--db", default="daily_report.db", help="SQLite 文件路径")
    return parser


def _build_sources(settings: Settings) -> SourceBundle:
    if settings.source_mode == "mock":
        return MockSourceBundle()

    client = httpx.Client()
    return SourceBundle(
        commit_source=GitHubCommitSource(client, settings.github_token or ""),
        task_source=FeishuTaskSource(
            client, settings.feishu_app_id or "", settings.feishu_app_secret or ""
        ),
        message_source=FeishuMessageSource(
            client, settings.feishu_app_id or "", settings.feishu_app_secret or ""
        ),
    )


def _build_publishers(settings: Settings) -> PublisherBundle:
    bot = None
    if settings.feishu_bot_webhook:
        bot = WebhookBotPublisher(
            httpx.Client(), webhook=settings.feishu_bot_webhook
        )
    return PublisherBundle(email=SmtpEmailPublisher(settings), bot=bot)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    settings = load_settings()
    repo = Repository(init_db(args.db))

    try:
        summary = run_daily(
            args.team,
            args.date,
            settings=settings,
            repo=repo,
            sources=_build_sources(settings),
            publishers=_build_publishers(settings),
        )
    except ReportError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 1

    print(f"status: {summary.status}")
    if summary.status == "skipped":
        print("重复触发已忽略（当日已有成功运行）")
    print(
        json.dumps(
            {
                "collected": summary.collected,
                "sent": summary.sent,
                "failed": summary.failed,
            },
            ensure_ascii=False,
        )
    )
    return 0