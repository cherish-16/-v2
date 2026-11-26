"""命令行入口。

退出码：0 成功或重复触发；2 参数错误。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


def resolve_default_date(tz_name: str, now: datetime | None = None) -> date:
    """按团队时区取"今天"。

    定时任务常跑在 UTC 机器上；直接用本地日期会让 16:00–24:00 的补跑
    落到前一天，与 run_daily 的日窗口错位。
    """
    moment = now or datetime.now(UTC)
    try:
        zone = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        zone = UTC
    return moment.astimezone(zone).date()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="daily_report")
    sub = parser.add_subparsers(dest="command", required=True)

    members = sub.add_parser("members", help="成员配置维护")
    members_sub = members.add_subparsers(dest="members_command", required=True)
    imp = members_sub.add_parser("import", help="从 JSON 文件导入成员")
    imp.add_argument("--file", required=True, help="members.json 路径")
    imp.add_argument("--db", default="daily_report.db", help="SQLite 文件路径")
    lst = members_sub.add_parser("list", help="列出已配置成员")
    lst.add_argument("--db", default="daily_report.db", help="SQLite 文件路径")

    run = sub.add_parser("run", help="生成并推送指定日期的日报")
    run.add_argument("--team", required=True, help="团队标识")
    run.add_argument(
        "--date", type=_parse_date, default=None, help="YYYY-MM-DD（默认取团队时区今天）"
    )
    run.add_argument("--print", dest="print_report", action="store_true",
                     help="在终端打印日报正文")
    run.add_argument("--force", action="store_true",
                     help="强制重跑并重新推送（忽略当天的幂等记录）")
    run.add_argument("--demo", action="store_true",
                     help="使用内置演示数据（无需任何外部凭证）")
    run.add_argument("--db", default="daily_report.db", help="SQLite 文件路径")
    return parser


def _handle_members(args: argparse.Namespace) -> int:
    """``members import`` / ``members list`` 的实现。"""
    from daily_report.members import MemberFileError, load_member_file

    repo = Repository(init_db(args.db))
    if args.members_command == "list":
        members = repo.list_members()
        if not members:
            print("（尚未配置成员）")
            return 0
        for m in members:
            missing = [
                name
                for name, value in (
                    ("github_login", m.github_login),
                    ("feishu_open_id", m.feishu_open_id),
                    ("email", m.email),
                )
                if not value
            ]
            gap = f"  缺少：{', '.join(missing)}" if missing else ""
            print(f"{m.member_id}	{m.name}{gap}")
        return 0

    try:
        members = load_member_file(args.file)
    except MemberFileError as exc:
        print(f"成员文件错误：{exc}", file=sys.stderr)
        return 1
    repo.upsert_members(members)
    print(f"已导入 {len(members)} 名成员")
    return 0


def _build_sources(settings: Settings, demo: bool = False) -> SourceBundle:
    if settings.source_mode == "mock" or demo:
        return MockSourceBundle() if not demo else _demo_bundle()

    client = httpx.Client(verify=not settings.insecure_tls)
    return SourceBundle(
        commit_source=GitHubCommitSource(
            client, settings.github_token or "", branch=settings.github_branch
        ),
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
            httpx.Client(verify=not settings.insecure_tls),
            webhook=settings.feishu_bot_webhook,
        )
    return PublisherBundle(email=SmtpEmailPublisher(settings), bot=bot)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    if args.command == "members":
        return _handle_members(args)

    settings = load_settings()
    run_date = args.date or resolve_default_date(settings.timezone)
    repo = Repository(init_db(args.db))

    try:
        if args.demo and not repo.list_members():
            from daily_report.models import Member

            repo.upsert_members([Member(**m) for m in DEMO_MEMBERS])

        if not repo.list_members():
            print(
                "没有成员配置。请先导入成员：\n"
                "  python -m daily_report members import --file members.json",
                file=sys.stderr,
            )
            return 1

        summary = run_daily(
            args.team,
            run_date,
            settings=settings,
            repo=repo,
            sources=_build_sources(settings, demo=args.demo),
            publishers=_build_publishers(settings),
            force=args.force,
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
    if args.print_report:
        _print_report(repo, args.team, run_date)
    return 0 if summary.status in ("success", "partial", "skipped") else 1


def _demo_bundle():
    """内置演示数据：三人、若干提交/任务/消息/考勤，无需任何外部凭证。"""
    from datetime import time, timedelta

    from daily_report.models import (
        AttendanceRecord,
        CommitRecord,
        MessageRecord,
        TaskRecord,
    )

    base = datetime.now(UTC).replace(hour=2, minute=0, second=0, microsecond=0)
    records = {
        "commits": [
            CommitRecord(
                sha=f"demo{i}",
                author_login=login,
                message=msg,
                committed_at=base + timedelta(minutes=i * 10),
                repo="demo-org/demo-repo",
            )
            for i, (login, msg) in enumerate(
                [
                    ("zhangsan", "修复登录接口超时问题"),
                    ("zhangsan", "补充分页边界处理"),
                    ("lisi", "补充单元测试覆盖"),
                    ("lisi", "调整日报模板排版"),
                    ("wangwu", "整理接口文档"),
                ]
            )
        ],
        "tasks": [
            TaskRecord(
                task_id="task-1",
                title="日报生成模块联调",
                status="done",
                assignee_open_id="ou_zhangsan",
                updated_at=base,
            ),
            TaskRecord(
                task_id="task-2",
                title="飞书推送验证",
                status="open",
                assignee_open_id="ou_lisi",
                updated_at=base,
            ),
        ],
        "messages": [
            MessageRecord(
                msg_id="msg-1",
                sender_open_id="ou_zhangsan",
                content="接口已经提 PR，请帮忙 review",
                created_at=base,
                chat_id="demo-chat",
            ),
            MessageRecord(
                msg_id="msg-2",
                sender_open_id="ou_wangwu",
                content="今天的日报模板我调整好了",
                created_at=base,
                chat_id="demo-chat",
            ),
        ],
        "attendance": [
            AttendanceRecord(
                record_id="att-1",
                member_open_id="ou_zhangsan",
                work_date=datetime.now(UTC).date(),
                status="present",
                checked_in_at=base.replace(hour=1, minute=12),
                checked_out_at=None,
            ),
            AttendanceRecord(
                record_id="att-2",
                member_open_id="ou_lisi",
                work_date=datetime.now(UTC).date(),
                status="late",
                checked_in_at=base.replace(hour=2, minute=30),
                checked_out_at=None,
            ),
            AttendanceRecord(
                record_id="att-3",
                member_open_id="ou_wangwu",
                work_date=datetime.now(UTC).date(),
                status="leave",
                checked_in_at=None,
                checked_out_at=None,
            ),
        ],
    }
    del time
    return MockSourceBundle(**records)


def _demo_email() -> str:
    """演示模式的收件地址：显式环境变量优先，其次读 .env。"""
    import os

    explicit = os.environ.get("DAILY_REPORT_DEMO_EMAIL")
    if explicit is not None:
        return explicit
    from daily_report.config import _env_file_values

    return _env_file_values().get("DAILY_REPORT_DEMO_EMAIL", "")

DEMO_MEMBERS = [
    {"member_id": "m1", "name": "张三", "github_login": "zhangsan",
     "feishu_open_id": "ou_zhangsan", "email": _demo_email()},
    {"member_id": "m2", "name": "李四", "github_login": "lisi",
     "feishu_open_id": "ou_lisi", "email": _demo_email()},
    {"member_id": "m3", "name": "王五", "github_login": "wangwu",
     "feishu_open_id": "ou_wangwu", "email": _demo_email()},
]


def _print_report(repo: Repository, team_id: str, run_date: date) -> None:
    """把团队日报渲染到终端 —— 没配邮件/飞书时也能看到产出。"""
    from daily_report.models import ReportScope
    from daily_report.render.text import render_team_text

    report = repo.get_report(ReportScope.TEAM, team_id, run_date)
    print()
    print("=" * 60)
    if report is None:
        print("（本次未生成团队日报）")
    else:
        print(render_team_text(report))
    print("=" * 60)