import smtplib
from datetime import UTC, date, datetime

import pytest

from daily_report.config import load_settings
from daily_report.errors import ConfigError
from daily_report.models import DailyReport, ReportScope
from daily_report.publishers.email import SmtpEmailPublisher, mask_email

T = datetime(2026, 11, 25, 10, tzinfo=UTC)


def _report():
    return DailyReport(
        scope=ReportScope.PERSONAL,
        entity_id="m1",
        report_date=date(2026, 11, 25),
        items=[],
        generated_at=T,
    )


def _settings():
    return load_settings(
        {
            "SMTP_HOST": "smtp.test",
            "SMTP_PORT": "465",
            "SMTP_USER": "bot@test",
            "SMTP_PASSWORD": "pw",
        }
    )


def test_mask_email():
    assert mask_email("zhangsan@example.com") == "z***@example.com"


def test_partial_failure_does_not_stop_batch():
    sent = []

    def send_fn(msg, recipients):
        if recipients == "bad@test":
            raise smtplib.SMTPException("boom")
        sent.append(recipients)

    publisher = SmtpEmailPublisher(_settings(), send_fn=send_fn)
    result = publisher.send_email(_report(), ["a@test", "bad@test", "c@test"])
    assert result.success == ["a@test", "c@test"]
    assert [r for r, _ in result.failed] == ["bad@test"]
    assert sent == ["a@test", "c@test"]


def test_auth_failure_stops_whole_batch():
    calls = []

    def send_fn(msg, recipients):
        calls.append(recipients)
        raise smtplib.SMTPAuthenticationError(535, b"auth")

    publisher = SmtpEmailPublisher(_settings(), send_fn=send_fn)
    result = publisher.send_email(_report(), ["a@test", "b@test"])
    assert len(calls) == 1
    assert len(result.failed) == 2


def test_failure_reason_does_not_leak_full_address():
    def send_fn(msg, recipients):
        raise smtplib.SMTPException("failed for secret@test")

    publisher = SmtpEmailPublisher(_settings(), send_fn=send_fn)
    result = publisher.send_email(_report(), ["bad@test"])
    reason = result.failed[0][1]
    assert "bad@test" not in reason


def test_missing_smtp_config_raises_config_error():
    publisher = SmtpEmailPublisher(load_settings({}))
    with pytest.raises(ConfigError):
        publisher.send_email(_report(), ["a@test"])