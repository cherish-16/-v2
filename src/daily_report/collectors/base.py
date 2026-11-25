"""采集端口定义。

真实实现与 Mock 实现共享这些 Protocol —— 调用方只依赖端口，不依赖具体数据源。
时间语义统一：``since`` 含、``until`` 不含，且必须为 UTC aware。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from daily_report.models import CommitRecord, MessageRecord, TaskRecord


@runtime_checkable
class CommitSource(Protocol):
    def collect_commits(
        self,
        owner: str,
        repo: str,
        since: datetime,
        until: datetime,
        *,
        max_pages: int = 10,
    ) -> list[CommitRecord]: ...


@runtime_checkable
class TaskSource(Protocol):
    def collect_tasks(self, since: datetime, until: datetime) -> list[TaskRecord]: ...


@runtime_checkable
class MessageSource(Protocol):
    def collect_messages(
        self, since: datetime, until: datetime
    ) -> list[MessageRecord]: ...


@dataclass
class SourceBundle:
    """一次运行使用的全部数据源。"""

    commit_source: CommitSource
    task_source: TaskSource
    message_source: MessageSource
    attendance_source: object | None = field(default=None)