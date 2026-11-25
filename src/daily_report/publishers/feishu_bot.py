"""飞书群机器人推送（webhook）。"""

from __future__ import annotations

import httpx

from daily_report.errors import ConfigError, TransientError
from daily_report.models import DailyReport
from daily_report.net import post_json
from daily_report.publishers.base import PushResult
from daily_report.render.text import render_text


class WebhookBotPublisher:
    def __init__(
        self,
        client: httpx.Client,
        webhook: str | None = None,
        retry_times: int = 2,
    ) -> None:
        self._client = client
        self._webhook = webhook
        self._retry_times = retry_times

    def push_to_feishu(
        self, report: DailyReport, webhook: str | None = None
    ) -> PushResult:
        url = webhook or self._webhook
        if not url:
            raise ConfigError("feishu bot webhook is not configured")

        body = {
            "msg_type": "text",
            "content": {"text": render_text(report)},
        }
        try:
            data = post_json(
                self._client, url, json_body=body, retry_times=self._retry_times
            )
        except TransientError as exc:
            return PushResult(ok=False, error=str(exc))

        if data.get("code") not in (0, None):
            return PushResult(
                ok=False,
                error=f"feishu returned code={data.get('code')} msg={data.get('msg')}",
            )
        return PushResult(ok=True)