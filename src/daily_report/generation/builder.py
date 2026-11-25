"""日报构建：归组结果 → DailyReport。

关键约定：
- ``scope`` 必填、无默认值 —— 必须显式说清是个人还是团队日报。
- 无数据日返回带 ``note="无数据"`` 的日报，绝不返回 ``None``。
- 每条条目的 ``source_id`` 必须非空，否则抛 ``TraceabilityError``。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime

from daily_report.errors import TraceabilityError
from daily_report.generation.attribution import AttributionResult, MemberData, attribute
from daily_report.models import (
    CommitRecord,
    DailyReport,
    Member,
    MessageRecord,
    ReportItem,
    ReportScope,
    TaskRecord,
)


def _to_items(data: MemberData) -> list[ReportItem]:
    """按「提交 → 任务 → 消息 → 考勤」的固定顺序生成条目。"""
    items: list[ReportItem] = []

    for commit in data.commits:
        _require(commit.sha, "github")
        items.append(
            ReportItem(
                source_type="github",
                source_id=commit.sha,
                text=commit.message.splitlines()[0] if commit.message else "(无提交说明)",
                occurred_at=commit.committed_at,
            )
        )
    for task in data.tasks:
        _require(task.task_id, "feishu_task")
        items.append(
            ReportItem(
                source_type="feishu_task",
                source_id=task.task_id,
                text=f"{task.title}（{task.status}）",
                occurred_at=task.updated_at,
            )
        )
    for message in data.messages:
        _require(message.msg_id, "feishu_message")
        prefix = "[已撤回] " if message.is_recalled else ""
        items.append(
            ReportItem(
                source_type="feishu_message",
                source_id=message.msg_id,
                text=f"{prefix}{message.content}",
                occurred_at=message.created_at,
            )
        )
    return items


def _require(source_id: str, source_type: str) -> None:
    if not source_id:
        raise TraceabilityError(
            f"{source_type} record has empty source id; cannot build a traceable item"
        )


def _compose_note(
    *,
    has_items: bool,
    missing_sources: Sequence[str],
    unmapped_names: Sequence[str] = (),
    no_data_names: Sequence[str] = (),
) -> str | None:
    parts: list[str] = []
    if not has_items:
        parts.append("无数据")
    if missing_sources:
        parts.append(f"来源缺失：{', '.join(missing_sources)}")
    if unmapped_names:
        parts.append(f"未配置映射成员：{'、'.join(unmapped_names)}")
    if no_data_names:
        parts.append(f"无数据成员：{'、'.join(no_data_names)}")
    return "；".join(parts) if parts else None


def generate_report(
    scope: ReportScope,
    entity_id: str,
    report_date: date,
    *,
    members: Sequence[Member],
    commits: Sequence[CommitRecord],
    tasks: Sequence[TaskRecord],
    messages: Sequence[MessageRecord],
    missing_sources: Sequence[str] = (),
    now: datetime | None = None,
) -> DailyReport:
    generated_at = now or datetime.now(UTC)
    result = attribute(members, commits, tasks, messages)

    if scope is ReportScope.PERSONAL:
        data = result.by_member.get(entity_id, MemberData())
        items = _to_items(data)
        return DailyReport(
            scope=scope,
            entity_id=entity_id,
            report_date=report_date,
            items=items,
            generated_at=generated_at,
            note=_compose_note(has_items=bool(items), missing_sources=missing_sources),
        )

    if scope is ReportScope.TEAM:
        return _build_team(
            entity_id=entity_id,
            report_date=report_date,
            members=members,
            result=result,
            missing_sources=missing_sources,
            generated_at=generated_at,
        )

    raise ValueError(f"unsupported scope: {scope!r}")


def _build_team(
    *,
    entity_id: str,
    report_date: date,
    members: Sequence[Member],
    result: AttributionResult,
    missing_sources: Sequence[str],
    generated_at: datetime,
) -> DailyReport:
    """把全组成员条目汇总成团队日报。

    按 ``members`` 的声明顺序遍历，保证输出稳定；条目文本加成员名前缀，
    渲染层据此分组。无数据成员与未配置映射成员都显式写进备注 ——
    一个人从日报里静默消失，比写错更糟。
    """
    items: list[ReportItem] = []
    no_data_names: list[str] = []

    for member in members:
        data = result.by_member.get(member.member_id, MemberData())
        member_items = _to_items(data)
        if not member_items:
            no_data_names.append(member.name)
        for item in member_items:
            items.append(
                ReportItem(
                    source_type=item.source_type,
                    source_id=item.source_id,
                    text=f"{member.name}：{item.text}",
                    occurred_at=item.occurred_at,
                )
            )

    return DailyReport(
        scope=ReportScope.TEAM,
        entity_id=entity_id,
        report_date=report_date,
        items=items,
        generated_at=generated_at,
        note=_compose_note(
            has_items=bool(items),
            missing_sources=missing_sources,
            unmapped_names=[m.name for m in result.unmapped],
            no_data_names=no_data_names,
        ),
    )
