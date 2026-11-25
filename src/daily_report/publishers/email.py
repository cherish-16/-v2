"""SMTP 邮件推送。

两条纪律：
1. 单个收件人失败不中断整批（CR-003）；认证失败则整批立即停止。
2. 日志与失败原因中的邮箱一律脱敏（NFR-S3）。
"""

from __future__ import annotations

import smtplib
from collections.abc import Callable, Sequence
from email.message import EmailMessage

from daily_report.config import Settings
from daily_report.errors import ConfigError
from daily_report.models import DailyReport
from daily_report.publishers.base import SendResult
from daily_report.render.text import render_email_html


def mask_email(address: str) -> str:
    """``zhangsan@example.com`` → ``z***@example.com``。"""
    if "@" not in address:
        return "***"
    local, _, domain = address.partition("@")
    head = local[:1] if local else ""
    return f"{head}***@{domain}"


def _safe_reason(exc: Exception) -> str:
    """异常文本可能包含地址，统一按类型给原因，不转发原始消息。"""
    return type(exc).__name__


class SmtpEmailPublisher:
    def __init__(
        self,
        settings: Settings,
        send_fn: Callable[[EmailMessage, str], None] | None = None,
    ) -> None:
        self._settings = settings
        self._send_fn = send_fn

    def send_email(
        self, report: DailyReport, recipients: Sequence[str]
    ) -> SendResult:
        self._require_config()

        html = render_email_html(report)
        subject = f"{report.report_date.isoformat()} 日报"
        result = SendResult()
        send = self._send_fn or self._send_via_smtp

        for index, recipient in enumerate(recipients):
            message = EmailMessage()
            message["Subject"] = subject
            message["From"] = self._settings.smtp_user or ""
            message["To"] = recipient
            message.set_content(html, subtype="html")
            try:
                send(message, recipient)
            except smtplib.SMTPAuthenticationError as exc:
                # 认证失败重试无意义，且后续收件人同样会失败：整批停止。
                result.failed.append((recipient, _safe_reason(exc)))
                for skipped in recipients[index + 1 :]:
                    result.failed.append((skipped, "skipped: authentication failed"))
                break
            except Exception as exc:  # noqa: BLE001 - 单封失败不能拖垮整批
                result.failed.append((recipient, _safe_reason(exc)))
            else:
                result.success.append(recipient)
        return result

    def _require_config(self) -> None:
        missing = [
            name
            for name in ("smtp_host", "smtp_user", "smtp_password")
            if not getattr(self._settings, name)
        ]
        if missing:
            raise ConfigError(f"SMTP configuration missing: {', '.join(missing)}")

    def _send_via_smtp(self, message: EmailMessage, _recipient: str) -> None:
        with smtplib.SMTP_SSL(
            self._settings.smtp_host or "", self._settings.smtp_port
        ) as server:
            server.login(
                self._settings.smtp_user or "", self._settings.smtp_password or ""
            )
            server.send_message(message)