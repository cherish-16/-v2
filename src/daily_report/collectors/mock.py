"""离线数据源：与真实实现同契约，用于演示与测试。

凭证未就绪时用它跑通全流程 —— 这正是 design.md ADR-004「数据源可替换」
要解决的问题。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from daily_report.collectors.base import SourceBundle
from daily_report.models import (
    AttendanceRecord,
    CommitRecord,
    MessageRecord,
    TaskRecord,
    ensure_utc,
)


def _check_window(since: datetime, until: datetime) -> tuple[datetime, datetime]:
    """校验并归一窗口边界。

    必须在过滤之前调用：即使没有任何记录，非法窗口也要立刻暴露，
    而不是因为"没有记录可比较"而静默通过。
    """
    return ensure_utc(since), ensure_utc(until)


def _in_window(moment: datetime, start: datetime, end: datetime) -> bool:
    """``since`` 含、``until`` 不含。"""
    return start <= ensure_utc(moment) < end


class MockCommitSource:
    def __init__(self, commits: Sequence[CommitRecord]) -> None:
        self._commits = list(commits)

    def collect_commits(
        self,
        owner: str,
        repo: str,
        since: datetime,
        until: datetime,
        *,
        max_pages: int = 10,
    ) -> list[CommitRecord]:
        start, end = _check_window(since, until)
        return [c for c in self._commits if _in_window(c.committed_at, start, end)]


class MockTaskSource:
    def __init__(self, tasks: Sequence[TaskRecord]) -> None:
        self._tasks = list(tasks)

    def collect_tasks(self, since: datetime, until: datetime) -> list[TaskRecord]:
        start, end = _check_window(since, until)
        return [t for t in self._tasks if _in_window(t.updated_at, start, end)]


class MockMessageSource:
    def __init__(self, messages: Sequence[MessageRecord]) -> None:
        self._messages = list(messages)

    def collect_messages(
        self, since: datetime, until: datetime
    ) -> list[MessageRecord]:
        start, end = _check_window(since, until)
        return [m for m in self._messages if _in_window(m.created_at, start, end)]


class MockAttendanceSource:
    def __init__(self, records: Sequence[AttendanceRecord]) -> None:
        self._records = list(records)

    def collect_attendance(
        self, since: datetime, until: datetime
    ) -> list[AttendanceRecord]:
        start, end = _check_window(since, until)
        # 缺勤记录没有打卡时间，按 work_date 落在窗口哪一天来判断
        return [
            r
            for r in self._records
            if start <= datetime.combine(
                r.work_date, datetime.min.time(), tzinfo=UTC
            ) < end
        ]


class MockSourceBundle(SourceBundle):
    """四个 Mock 采集器的组合，构造参数即演示数据。

    考勤源始终存在（空数据返回空列表）：这样「考勤源已配置但没有记录」
    与「未配置考勤源」在 Mock 路径下都是可运行的合法状态。
    """

    def __init__(
        self,
        commits: Sequence[CommitRecord] | None = None,
        tasks: Sequence[TaskRecord] | None = None,
        messages: Sequence[MessageRecord] | None = None,
        attendance: Sequence[AttendanceRecord] | None = None,
    ) -> None:
        super().__init__(
            commit_source=MockCommitSource(commits or []),
            task_source=MockTaskSource(tasks or []),
            message_source=MockMessageSource(messages or []),
            attendance_source=MockAttendanceSource(attendance or []),
        )