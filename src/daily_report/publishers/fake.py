"""测试与演示用推送器：记录调用，可开关失败。"""

from __future__ import annotations

from collections.abc import Sequence

from daily_report.models import DailyReport
from daily_report.publishers.base import PushResult, SendResult


class FakePublisher:
    """同时实现 ``EmailPublisher`` 与 ``BotPublisher``。"""

    def __init__(self, fail_email: bool = False, fail_bot: bool = False) -> None:
        self.fail_email = fail_email
        self.fail_bot = fail_bot
        self.email_calls: list[tuple[DailyReport, list[str]]] = []
        self.bot_calls: list[DailyReport] = []

    def send_email(
        self, report: DailyReport, recipients: Sequence[str]
    ) -> SendResult:
        self.email_calls.append((report, list(recipients)))
        if self.fail_email:
            return SendResult(
                success=[], failed=[(r, "fake failure") for r in recipients]
            )
        return SendResult(success=list(recipients), failed=[])

    def push_to_feishu(
        self, report: DailyReport, webhook: str | None = None
    ) -> PushResult:
        self.bot_calls.append(report)
        if self.fail_bot:
            return PushResult(ok=False, error="fake failure")
        return PushResult(ok=True)