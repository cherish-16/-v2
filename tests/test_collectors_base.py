from datetime import UTC, datetime

import pytest

from daily_report.collectors.base import CommitSource, SourceBundle
from daily_report.collectors.mock import MockSourceBundle
from daily_report.models import CommitRecord

SINCE = datetime(2026, 11, 25, tzinfo=UTC)
UNTIL = datetime(2026, 11, 26, tzinfo=UTC)


def test_mock_satisfies_protocols():
    bundle = MockSourceBundle()
    assert isinstance(bundle, SourceBundle)
    assert isinstance(bundle.commit_source, CommitSource)


def test_mock_returns_injected_commits():
    record = CommitRecord(
        sha="s1",
        author_login="u",
        message="m",
        committed_at=datetime(2026, 11, 25, 10, tzinfo=UTC),
        repo="o/r",
    )
    bundle = MockSourceBundle(commits=[record])
    result = bundle.commit_source.collect_commits("o", "r", SINCE, UNTIL)
    assert result == [record]


def test_mock_filters_by_time_window():
    before = CommitRecord(
        sha="old",
        author_login="u",
        message="m",
        committed_at=datetime(2026, 11, 24, 10, tzinfo=UTC),
        repo="o/r",
    )
    bundle = MockSourceBundle(commits=[before])
    assert bundle.commit_source.collect_commits("o", "r", SINCE, UNTIL) == []


def test_naive_datetime_rejected():
    bundle = MockSourceBundle()
    with pytest.raises(ValueError, match="must be timezone-aware"):
        bundle.commit_source.collect_commits(
            "o",
            "r",
            datetime(2026, 11, 25),
            UNTIL,
        )


def test_empty_window_returns_empty_list():
    bundle = MockSourceBundle()
    assert bundle.task_source.collect_tasks(UNTIL, UNTIL) == []