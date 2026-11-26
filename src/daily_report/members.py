"""成员配置文件加载（R-09：维护成员与采集映射配置）。

成员名单是最容易被忽略的配置项：没有它，程序不认识任何人，
生成出来的日报只能是空的。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from daily_report.models import Member


class MemberFileError(Exception):
    """成员文件格式错误。"""


def _require_text(entry: dict[str, Any], key: str, index: int) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MemberFileError(f"第 {index + 1} 条成员缺少必填字段 {key!r}")
    return value.strip()


def load_member_file(path: str | Path) -> list[Member]:
    """读取成员 JSON 文件。

    接受两种形态：顶层数组，或 ``{"members": [...]}``。
    ``member_id`` 与 ``name`` 必填；其余字段可为空字符串或省略。
    """
    file_path = Path(path)
    if not file_path.exists():
        raise MemberFileError(f"文件不存在：{file_path}")

    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MemberFileError(f"JSON 解析失败：{exc}") from exc

    entries = raw.get("members") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise MemberFileError("成员文件应为数组，或含 members 数组的对象")

    members: list[Member] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise MemberFileError(f"第 {index + 1} 条成员不是对象")
        member_id = _require_text(entry, "member_id", index)
        if member_id in seen:
            raise MemberFileError(f"member_id 重复：{member_id}")
        seen.add(member_id)
        members.append(
            Member(
                member_id=member_id,
                name=_require_text(entry, "name", index),
                github_login=(entry.get("github_login") or None),
                feishu_open_id=(entry.get("feishu_open_id") or None),
                email=(entry.get("email") or None),
                git_emails=tuple(entry.get("git_emails") or ()),
            )
        )

    if not members:
        raise MemberFileError("成员文件为空")
    return members