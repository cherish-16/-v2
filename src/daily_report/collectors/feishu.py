"""飞书开放平台采集：任务流转与群消息。

分页游标是内部实现细节，不暴露到对外契约（对应 CR-004 的驳回结论）：
调用方只说「按日取全量」。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx

from daily_report.errors import AuthenticationError
from daily_report.models import MessageRecord, TaskRecord, ensure_utc
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