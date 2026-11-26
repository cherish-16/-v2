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
    #: member_id → 缺少的映射字段名，例如 ``{"m2": ["github_login"]}``。
    #: 半配置成员（只配了飞书没配 GitHub）也在其中 —— 否则他们的提交会静默消失。
    mapping_gaps: dict[str, list[str]] = field(default_factory=dict)


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
    # GitHub 未关联账号的提交，author_login 是 "xxx(unmapped)" 之类的占位值，
    # 只能靠提交邮箱归属。按小写比较，避免大小写差异漏匹配。
    by_email: dict[str, str] = {}
    for m in members:
        for addr in m.git_emails:
            if addr:
                by_email[addr.strip().lower()] = m.member_id

    by_member: dict[str, MemberData] = {m.member_id: MemberData() for m in members}

    for commit in commits:
        member_id = by_login.get(commit.author_login)
        if member_id is None and commit.author_email:
            member_id = by_email.get(commit.author_email.strip().lower())
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

    # 映射缺口按渠道分别计算：只配了飞书的成员，GitHub 提交无法归属他们，
    # 但他们的飞书数据是能收进来的 —— 这既不是"完全未配置"，也不能静默放过。
    mapping_gaps: dict[str, list[str]] = {}
    for member in members:
        gaps = [
            name
            for name, value in (
                ("github_login", member.github_login or member.git_emails),
                ("feishu_open_id", member.feishu_open_id),
            )
            if not value
        ]
        if gaps and len(gaps) < 2:  # 两个都缺 = 完全未配置，归入 unmapped
            mapping_gaps[member.member_id] = gaps

    unmapped = [
        m
        for m in members
        if not m.github_login and not m.git_emails and not m.feishu_open_id
    ]
    return AttributionResult(
        by_member=by_member, unmapped=unmapped, mapping_gaps=mapping_gaps
    )