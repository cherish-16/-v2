"""领域数据结构。

无业务逻辑、无 IO。所有时间字段在构造时归一为 UTC aware，
naive datetime 一律拒绝——跨时区重复/漏采的根源就在这里。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum


def ensure_utc(value: datetime) -> datetime:
    """校验并归一为 UTC。

    naive datetime 抛 ValueError：调用方必须明确说自己指的是哪个时区，
    我们不做猜测。
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"datetime must be timezone-aware, got naive value: {value!r}")
    return value.astimezone(UTC)


class ReportScope(StrEnum):
    PERSONAL = "personal"
    TEAM = "team"


@dataclass(frozen=True)
class Member:
    member_id: str
    name: str
    github_login: str | None = None
    feishu_open_id: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class CommitRecord:
    sha: str
    author_login: str
    message: str
    committed_at: datetime
    repo: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "committed_at", ensure_utc(self.committed_at))


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    title: str
    status: str
    assignee_open_id: str | None
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))


@dataclass(frozen=True)
class MessageRecord:
    msg_id: str
    sender_open_id: str | None
    content: str
    created_at: datetime
    chat_id: str
    is_recalled: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))


ATTENDANCE_STATUSES = frozenset({"present", "absent", "late", "leave"})


@dataclass(frozen=True)
class AttendanceRecord:
    """考勤原始记录（v1.1 变更新增）。

    ``checked_in_at`` / ``checked_out_at`` 为 None 表示没有对应打点 ——
    缺勤日天然如此，不是数据缺失。
    """

    record_id: str
    member_open_id: str | None
    work_date: date
    status: str
    checked_in_at: datetime | None
    checked_out_at: datetime | None

    def __post_init__(self) -> None:
        if not self.record_id:
            raise ValueError("AttendanceRecord.record_id must be non-empty for traceability")
        if self.status not in ATTENDANCE_STATUSES:
            raise ValueError(
                f"AttendanceRecord.status must be one of {sorted(ATTENDANCE_STATUSES)}, "
                f"got {self.status!r}"
            )
        if self.checked_in_at is not None:
            object.__setattr__(self, "checked_in_at", ensure_utc(self.checked_in_at))
        if self.checked_out_at is not None:
            object.__setattr__(self, "checked_out_at", ensure_utc(self.checked_out_at))


@dataclass(frozen=True)
class ReportItem:
    source_type: str
    source_id: str
    text: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("ReportItem.source_id must be non-empty for traceability")
        object.__setattr__(self, "occurred_at", ensure_utc(self.occurred_at))


@dataclass
class DailyReport:
    scope: ReportScope
    entity_id: str
    report_date: date
    items: list[ReportItem] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    note: str | None = None

    def __post_init__(self) -> None:
        self.generated_at = ensure_utc(self.generated_at)


@dataclass
class RunSummary:
    team_id: str
    run_date: date
    status: str
    collected: dict = field(default_factory=dict)
    sent: dict = field(default_factory=dict)
    failed: dict = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        self.started_at = ensure_utc(self.started_at)
        if self.finished_at is not None:
            self.finished_at = ensure_utc(self.finished_at)
        if self.status not in {"success", "skipped", "partial", "failed"}:
            raise ValueError(f"invalid RunSummary.status: {self.status!r}")