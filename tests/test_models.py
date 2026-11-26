from datetime import UTC, datetime

import pytest

from daily_report.models import (
    CommitRecord,
    DailyReport,
    ReportItem,
    ReportScope,
    ensure_utc,
)


def test_ensure_utc_rejects_naive_datetime():
    with pytest.raises(ValueError, match="must be timezone-aware"):
        ensure_utc(datetime(2026, 11, 25, 10, 0))


def test_ensure_utc_converts_to_utc():
    result = ensure_utc(datetime(2026, 11, 25, 10, 0, tzinfo=UTC))
    assert result.tzinfo == UTC


def test_commit_record_rejects_naive_committed_at():
    with pytest.raises(ValueError, match="must be timezone-aware"):
        CommitRecord(
            sha="a1",
            author_login="u",
            message="m",
            committed_at=datetime(2026, 11, 25),
            repo="o/r",
        )


def test_daily_report_note_is_none_by_default():
    report = DailyReport(
        scope=ReportScope.PERSONAL,
        entity_id="m1",
        report_date=datetime(2026, 11, 25).date(),
        items=[],
        generated_at=datetime(2026, 11, 25, tzinfo=UTC),
    )
    assert report.note is None


def test_report_item_requires_non_empty_source_id():
    with pytest.raises(ValueError, match="source_id"):
        ReportItem(
            source_type="github",
            source_id="",
            text="t",
            occurred_at=datetime(2026, 11, 25, tzinfo=UTC),
        )