"""飞书开放平台采集：任务流转与群消息。

分页游标是内部实现细节，不暴露到对外契约（对应 CR-004 的驳回结论）：
调用方只说「按日取全量」。
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Sequence
from datetime import UTC, date, datetime

import httpx

from daily_report.errors import AuthenticationError
from daily_report.models import (
    AttendanceRecord,
    MessageRecord,
    TaskRecord,
    ensure_utc,
)
from daily_report.net import get_json, post_json

API_BASE = "https://open.feishu.cn/open-apis"
_TOKEN_PATH = "/auth/v3/tenant_access_token/internal"
MAX_PAGES = 20


def _epoch_ms_to_utc(raw: str) -> datetime:
    return datetime.fromtimestamp(int(raw) / 1000, tz=UTC)


def _iso_z(moment: datetime) -> str:
    return ensure_utc(moment).isoformat().replace("+00:00", "Z")


class _FeishuBase:
    def __init__(self, client: httpx.Client, app_id: str, app_secret: str) -> None:
        self._client = client
        self._app_id = app_id
        self._app_secret = app_secret
        self._token: str | None = None

    def _tenant_token(self) -> str:
        """获取并缓存 tenant access token。"""
        if self._token is not None:
            return self._token
        data = post_json(
            self._client,
            f"{API_BASE}{_TOKEN_PATH}",
            json_body={"app_id": self._app_id, "app_secret": self._app_secret},
        )
        token = data.get("tenant_access_token")
        if not token:
            raise AuthenticationError(
                f"feishu token request failed: code={data.get('code')} msg={data.get('msg')}"
            )
        self._token = token
        return token

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._tenant_token()}"}


class FeishuTaskSource(_FeishuBase):
    def collect_tasks(self, since: datetime, until: datetime) -> list[TaskRecord]:
        start = ensure_utc(since)
        end = ensure_utc(until)
        if start >= end:
            return []

        records: list[TaskRecord] = []
        page_token: str | None = None
        for _ in range(MAX_PAGES):
            params: dict[str, str] = {
                "completed_since": _iso_z(start),
                "completed_until": _iso_z(end),
                "page_size": "50",
            }
            if page_token:
                params["page_token"] = page_token
            data = get_json(
                self._client,
                f"{API_BASE}/task/v2/tasks",
                params=params,
                headers=self._auth_headers(),
            )
            payload = data.get("data", {})
            records.extend(
                self._to_record(item) for item in payload.get("items", [])
            )
            if not payload.get("has_more"):
                break
            page_token = payload.get("page_token")
            if not page_token:
                warnings.warn(
                    f"feishu task pagination truncated at {MAX_PAGES} pages "
                    "(has_more=True but no page_token)",
                    UserWarning,
                    stacklevel=1,
                )
                break
        else:
            warnings.warn(
                f"feishu task pagination truncated at {MAX_PAGES} pages",
                UserWarning,
                stacklevel=1,
            )

        return [r for r in records if start <= r.updated_at < end]

    @staticmethod
    def _to_record(item: dict) -> TaskRecord:
        assignee = None
        for member in item.get("members", []):
            if member.get("role") == "assignee":
                assignee = member.get("id")
                break
        return TaskRecord(
            task_id=item["id"],
            title=item.get("summary", ""),
            status="open" if item.get("completed_at", "0") == "0" else "done",
            assignee_open_id=assignee,
            updated_at=_epoch_ms_to_utc(item["updated_at"]),
        )


class FeishuMessageSource(_FeishuBase):
    def collect_messages(
        self, since: datetime, until: datetime
    ) -> list[MessageRecord]:
        start = ensure_utc(since)
        end = ensure_utc(until)
        if start >= end:
            return []

        records: list[MessageRecord] = []
        page_token: str | None = None
        for _ in range(MAX_PAGES):
            params: dict[str, str] = {
                "start_time": _iso_z(start),
                "end_time": _iso_z(end),
                "page_size": "50",
            }
            if page_token:
                params["page_token"] = page_token
            data = get_json(
                self._client,
                f"{API_BASE}/im/v1/messages",
                params=params,
                headers=self._auth_headers(),
            )
            payload = data.get("data", {})
            records.extend(
                self._to_record(item) for item in payload.get("items", [])
            )
            if not payload.get("has_more"):
                break
            page_token = payload.get("page_token")
            if not page_token:
                warnings.warn(
                    f"feishu message pagination truncated at {MAX_PAGES} pages "
                    "(has_more=True but no page_token)",
                    UserWarning,
                    stacklevel=1,
                )
                break
        else:
            warnings.warn(
                f"feishu message pagination truncated at {MAX_PAGES} pages",
                UserWarning,
                stacklevel=1,
            )

        return [r for r in records if start <= r.created_at < end]

    @staticmethod
    def _to_record(item: dict) -> MessageRecord:
        content = item.get("body", {}).get("content", "")
        text = content
        try:
            text = json.loads(content).get("text", content)
        except (ValueError, AttributeError):
            pass
        return MessageRecord(
            msg_id=item["message_id"],
            sender_open_id=(item.get("sender") or {}).get("id"),
            content=text,
            created_at=_epoch_ms_to_utc(item["create_time"]),
            chat_id=item.get("chat_id", ""),
            is_recalled=bool(item.get("deleted", False)),
        )

def _record_moment(record: AttendanceRecord) -> datetime:
    """考勤记录的时间基准：优先打卡时间，否则用工作日的 UTC 零点。"""
    if record.checked_in_at is not None:
        return record.checked_in_at
    return datetime.combine(record.work_date, datetime.min.time(), tzinfo=UTC)


class FeishuAttendanceSource(_FeishuBase):
    """考勤采集（v1.1 变更，见 design.md §3.6 / ADR-005）。

    飞书考勤接口要求显式给出要查询的人员列表（``user_ids``）和人员 ID 类型
    （``employee_type``）。空列表会返回 1220001，因此调用方必须提供成员。
    """

    def __init__(
        self,
        client: httpx.Client,
        app_id: str,
        app_secret: str,
        user_ids: Sequence[str] = (),
        employee_type: str = "employee_id",
    ) -> None:
        super().__init__(client, app_id, app_secret)
        self._user_ids = tuple(user_ids)
        self._employee_type = employee_type

    def collect_attendance(
        self, since: datetime, until: datetime
    ) -> list[AttendanceRecord]:
        start = ensure_utc(since)
        end = ensure_utc(until)
        if start >= end:
            return []

        records: list[AttendanceRecord] = []
        page_token: str | None = None
        for _ in range(MAX_PAGES):
            params: dict[str, str] = {
                "employee_type": self._employee_type,
                "page_size": "50",
            }
            if page_token:
                params["page_token"] = page_token
            # 该接口是 POST，日期用秒级时间戳，用户列表字段名是 employeeNos。
            data = post_json(
                self._client,
                f"{API_BASE}/attendance/v1/user_tasks/query",
                json_body={
                    "user_ids": list(self._user_ids),
                    "check_date_from": int(start.timestamp()),
                    "check_date_to": int(end.timestamp()),
                },
                params=params,
                headers=self._auth_headers(),
            )
            payload = data.get("data", {})
            records.extend(
                self._to_record(item) for item in payload.get("user_task_results", [])
            )
            if not payload.get("has_more"):
                break
            page_token = payload.get("page_token")
        # 服务端按日闭区间返回，这里再按 [start, end) 过滤一次，
        # 防止前一天/后一天的记录串进来。
        return [r for r in records if start <= _record_moment(r) < end]

    #: 飞书考勤状态词表 → 我们的领域词表。未知值降级为 present，
    #: 避免一个陌生状态码让整个来源失败。
    _STATUS_MAP = {
        "Normal": "present",
        "SystemCheck": "present",
        "Lack": "absent",
        "Late": "late",
        "Leave": "leave",
        "SickLeave": "leave",
        "AnnualLeave": "leave",
        "PersonalLeave": "leave",
    }

    @classmethod
    def _to_record(cls, item: dict) -> AttendanceRecord:
        check_in = item.get("check_in_record") or {}
        check_out = item.get("check_out_record") or {}
        raw_status = item.get("status") or "present"
        return AttendanceRecord(
            record_id=item.get("result_id") or item.get("user_id") or "unknown",
            member_open_id=item.get("user_id"),
            work_date=date.fromisoformat(item.get("day", "1970-01-01")),
            status=cls._STATUS_MAP.get(raw_status, "present"),
            checked_in_at=(
                _epoch_ms_to_utc(check_in["time"]) if check_in.get("time") else None
            ),
            checked_out_at=(
                _epoch_ms_to_utc(check_out["time"]) if check_out.get("time") else None
            ),
        )
