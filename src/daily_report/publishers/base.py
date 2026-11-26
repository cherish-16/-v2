"""推送端口与结果类型。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from daily_report.models import DailyReport


@dataclass
class SendResult:
    success: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


@dataclass
class PushResult:
    ok: bool
    error: str | None = None


@runtime_checkable
class EmailPublisher(Protocol):
    def send_email(
        self, report: DailyReport, recipients: Sequence[str]
    ) -> SendResult: ...


@runtime_checkable
class BotPublisher(Protocol):
    def push_to_feishu(self, report: DailyReport, webhook: str | None = None) -> PushResult: ...