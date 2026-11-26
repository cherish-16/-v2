"""每日运行编排。

职责：幂等控制、失败隔离、把各层结果汇总成 ``RunSummary``。
这是唯一允许同时依赖采集层、生成层与推送层的模块。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from daily_report.collectors.base import SourceBundle
from daily_report.config import Settings
from daily_report.generation.builder import generate_report
from daily_report.models import ReportScope, RunSummary
from daily_report.publishers.base import BotPublisher, EmailPublisher
from daily_report.publishers.email import mask_email
from daily_report.storage.repository import Repository

logger = logging.getLogger(__name__)


@dataclass
class PublisherBundle:
    email: EmailPublisher
    bot: BotPublisher | None = None


def _day_window(report_date: date, tz_name: str) -> tuple[datetime, datetime]:
    """把「团队时区的一天」换算成 UTC 半开区间 [start, end)。"""
    try:
        zone = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 - 时区名非法时退回 UTC，不让整批失败
        logger.warning("unknown timezone %r, falling back to UTC", tz_name)
        zone = UTC
    start = datetime.combine(report_date, time.min, tzinfo=zone)
    end = start + timedelta(days=1)
    return start.astimezone(UTC), end.astimezone(UTC)


def run_daily(
    team_id: str,
    report_date: date,
    *,
    settings: Settings,
    repo: Repository,
    sources: SourceBundle,
    publishers: PublisherBundle,
    now: datetime | None = None,
    force: bool = False,
) -> RunSummary:
    started_at = now or datetime.now(UTC)
    if started_at.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    existing = repo.find_latest_run(team_id, report_date)
    if not force and existing is not None and existing.status in ("success", "partial"):
        logger.info("duplicate run for %s on %s ignored", team_id, report_date)
        return RunSummary(
            team_id=team_id,
            run_date=report_date,
            status="skipped",
            collected=existing.collected,
            sent=existing.sent,
            failed=existing.failed,
            started_at=started_at,
            finished_at=started_at,
        )

    since, until = _day_window(report_date, settings.timezone)
    collected: dict[str, int] = {}
    failed: dict[str, str] = {}
    missing_sources: list[str] = []

    # ---- 采集：单源失败不影响其余 ----
    commits = []
    try:
        owner = settings.github_owner or "demo-org"
        repo_name = settings.github_repo or "demo-repo"
        if settings.source_mode == "live" and (
            not settings.github_owner or not settings.github_repo
        ):
            raise ValueError("GITHUB_OWNER and GITHUB_REPO must be configured in live mode")
        commits = sources.commit_source.collect_commits(
            owner,
            repo_name,
            since,
            until,
            max_pages=settings.max_pages,
        )
        repo.save_commits(commits)
        collected["github"] = len(commits)
    except Exception as exc:  # noqa: BLE001 - 失败隔离是设计目标
        failed["github"] = type(exc).__name__
        missing_sources.append("github")

    tasks = []
    try:
        tasks = sources.task_source.collect_tasks(since, until)
        repo.save_tasks(tasks)
        collected["feishu_task"] = len(tasks)
    except Exception as exc:  # noqa: BLE001
        failed["feishu_task"] = type(exc).__name__
        missing_sources.append("feishu_task")

    messages = []
    try:
        messages = sources.message_source.collect_messages(since, until)
        repo.save_messages(messages)
        collected["feishu_message"] = len(messages)
    except Exception as exc:  # noqa: BLE001
        failed["feishu_message"] = type(exc).__name__
        missing_sources.append("feishu_message")

    # 考勤源可选：未配置时整段跳过，行为与变更前一致
    attendance = []
    if sources.attendance_source is not None:
        try:
            attendance = sources.attendance_source.collect_attendance(since, until)
            collected["feishu_attendance"] = len(attendance)
        except Exception as exc:  # noqa: BLE001
            failed["feishu_attendance"] = type(exc).__name__
            missing_sources.append("feishu_attendance")

    # ---- 生成：每个成员一份 + 团队一份 ----
    members = repo.list_members()
    if not members:
        # 没有成员就没有日报可生成；判 success 会把当天永久锁死。
        failed["members"] = "no members configured; nothing to generate"
    personal_reports = []
    for member in members:
        try:
            report = generate_report(
            ReportScope.PERSONAL,
            member.member_id,
            report_date,
            members=members,
            commits=commits,
            tasks=tasks,
            messages=messages,
            attendance=attendance,
            missing_sources=missing_sources,
                now=started_at,
                tz=settings.timezone,
            )
        except Exception as exc:  # noqa: BLE001 - 单人失败不得拖垮整批
            failed[f"personal:{member.member_id}"] = type(exc).__name__
            continue
        repo.save_report(report)
        personal_reports.append(report)

    team_report = None
    try:
        team_report = generate_report(
        ReportScope.TEAM,
        team_id,
        report_date,
        members=members,
        commits=commits,
        tasks=tasks,
        messages=messages,
        attendance=attendance,
        missing_sources=missing_sources,
        now=started_at,
            tz=settings.timezone,
        )
    except Exception as exc:  # noqa: BLE001
        failed["team_report"] = type(exc).__name__
    else:
        repo.save_report(team_report)

    # ---- 推送：两个渠道各自隔离（I1）----
    sent: dict[str, int] = {}
    email_ok = bot_ok = False
    had_channels = False

    # 去重并保持稳定顺序：同一地址只发一次，避免一人配置多条成员记录导致重复收信。
    recipients = list(dict.fromkeys(m.email for m in members if m.email))
    if recipients:
        had_channels = True
        try:
            result = publishers.email.send_email(team_report, recipients)
            sent["email"] = len(result.success)
            email_ok = bool(result.success)
            for address, reason in result.failed:
                failed[f"email:{mask_email(address)}"] = reason
        except Exception as exc:  # noqa: BLE001 - 单渠道失败不得中断
            failed["email"] = type(exc).__name__
    else:
        sent["email"] = 0

    if publishers.bot is not None and team_report is not None:
        had_channels = True
        try:
            push = publishers.bot.push_to_feishu(team_report)
            sent["feishu_bot"] = 1 if push.ok else 0
            bot_ok = push.ok
            if not push.ok:
                failed["feishu_bot"] = push.error or "unknown"
        except Exception as exc:  # noqa: BLE001
            sent["feishu_bot"] = 0
            failed["feishu_bot"] = type(exc).__name__

    finished_at = datetime.now(UTC) if now is None else started_at
    # 没有任何成员 = 本次运行没有产出，判 failed 以便配置修正后可重试。
    # 有渠道但全挂 → failed；部分失败 → partial；全好 → success。
    if not members:
        status = "failed"
    elif failed and had_channels and not (email_ok or bot_ok):
        status = "failed"
    elif failed:
        status = "partial"
    else:
        status = "success"

    summary = RunSummary(
        team_id=team_id,
        run_date=report_date,
        status=status,
        collected=collected,
        sent=sent,
        failed=failed,
        started_at=started_at,
        finished_at=finished_at,
    )
    repo.save_run_summary(summary)
    return summary