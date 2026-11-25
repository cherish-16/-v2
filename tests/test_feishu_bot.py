from datetime import UTC, date, datetime

import httpx
import pytest

from daily_report.errors import ConfigError
from daily_report.models import DailyReport, ReportScope
from daily_report.publishers.feishu_bot import WebhookBotPublisher


def _report():
    return DailyReport(
        scope=ReportScope.TEAM,
        entity_id="t1",
        report_date=date(2026, 11, 25),
        items=[],
        generated_at=datetime(2026, 11, 25, tzinfo=UTC),
    )


def _publisher(handler, webhook="https://hook.test/x"):
    return WebhookBotPublisher(
        httpx.Client(transport=httpx.MockTransport(handler)),
        webhook=webhook,
    )


def test_success_returns_ok():
    publisher = _publisher(lambda r: httpx.Response(200, json={"code": 0}))
    assert publisher.push_to_feishu(_report()).ok is True


def test_5xx_retried_then_reports_failure():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    result = _publisher(handler).push_to_feishu(_report())
    assert result.ok is False
    assert len(calls) == 3


def test_missing_webhook_raises_config_error():
    publisher = _publisher(lambda r: httpx.Response(200), webhook=None)
    with pytest.raises(ConfigError):
        publisher.push_to_feishu(_report())


def test_feishu_business_error_reports_failure():
    publisher = _publisher(
        lambda r: httpx.Response(200, json={"code": 19001, "msg": "bad"})
    )
    result = publisher.push_to_feishu(_report())
    assert result.ok is False
    assert "19001" in result.error