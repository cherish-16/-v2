"""协作归属：把原始记录按账号映射归到成员名下。

两条硬规则：
1. 映射缺失的成员不参与归组，直接列入 ``unmapped`` —— 绝不按姓名相似度猜测。
2. 只按提交作者 / 任务负责人归组，不按群消息发言者推测协作关系。

纯函数，无 IO。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from daily_report.models import (
    AttendanceRecord,
    CommitRecord,
    Member,
    MessageRecord,
    TaskRecord,
)


@dataclass
class MemberData:
    commits: list[CommitRecord] = field(default_factory=list)
    tasks: list[TaskRecord] = field(default_factory=list)
    messages: list[MessageRecord] = field(default_factory=list)
    attendance: list[AttendanceRecord] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.commits or self.tasks or self.messages or self.attendance)


@dataclass
class AttributionResult:
    by_member: dict[str, MemberData]
    unmapped: list[Member]


def attribute(
    members: Sequence[Member],
    commits: Sequence[CommitRecord],
    tasks: Sequence[TaskRecord],
    messages: Sequence[MessageRecord],
    attendance: Sequence[AttendanceRecord] = (),
) -> AttributionResult:
    by_login = {
        m.github_login: m.member_id for m in members if m.github_login
    }
    by_open_id = {
        m.feishu_open_id: m.member_id for m in members if m.feishu_open_id
    }

    by_member: dict[str, MemberData] = {m.member_id: MemberData() for m in members}

    for commit in commits:
        member_id = by_login.get(commit.author_login)
        if member_id is not None:
            by_member[member_id].commits.append(commit)

    for task in tasks:
        member_id = by_open_id.get(task.assignee_open_id or "")
        if member_id is not None:
            by_member[member_id].tasks.append(task)

    for message in messages:
        member_id = by_open_id.get(message.sender_open_id or "")
        if member_id is not None:
            by_member[member_id].messages.append(message)

    for record in attendance:
        member_id = by_open_id.get(record.member_open_id or "")
        if member_id is not None:
            by_member[member_id].attendance.append(record)

    unmapped = [
        m for m in members if not m.github_login and not m.feishu_open_id
    ]
    return AttributionResult(by_member=by_member, unmapped=unmapped)