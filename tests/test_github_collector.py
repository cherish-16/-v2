from datetime import UTC, datetime

import httpx
import pytest

from daily_report.collectors.github import GitHubCommitSource
from daily_report.errors import AuthenticationError, TransientError

SINCE = datetime(2026, 11, 25, tzinfo=UTC)
UNTIL = datetime(2026, 11, 26, tzinfo=UTC)


def _commit(sha, when, login="zhangsan"):
    return {
        "sha": sha,
        "commit": {"message": f"work {sha}", "author": {"date": when}},
        "author": {"login": login},
    }


def _source(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GitHubCommitSource(client, token="tok")


def test_collects_and_maps_fields():
    def handler(request):
        assert request.headers["Authorization"] == "Bearer tok"
        return httpx.Response(200, json=[_commit("s1", "2026-11-25T10:00:00Z")])

    result = _source(handler).collect_commits("o", "r", SINCE, UNTIL)
    assert len(result) == 1
    record = result[0]
    assert record.sha == "s1"
    assert record.author_login == "zhangsan"
    assert record.repo == "o/r"
    assert record.committed_at == datetime(2026, 11, 25, 10, tzinfo=UTC)
    assert record.committed_at.tzinfo is not None


def test_empty_window_returns_empty_list():
    def handler(request):
        return httpx.Response(200, json=[])

    assert _source(handler).collect_commits("o", "r", SINCE, SINCE) == []


def test_401_raises_authentication_error():
    def handler(request):
        return httpx.Response(401)

    with pytest.raises(AuthenticationError):
        _source(handler).collect_commits("o", "r", SINCE, UNTIL)


def test_pagination_stops_at_max_pages(caplog):
    """每页都满（100 条）时应在 max_pages 处截断并告警。"""

    def handler(request):
        return httpx.Response(
            200,
            json=[_commit(f"s{i}", "2026-11-25T10:00:00Z") for i in range(100)],
        )

    with caplog.at_level("WARNING"):
        result = _source(handler).collect_commits("o", "r", SINCE, UNTIL, max_pages=2)
    assert len(result) == 200
    assert "truncated" in caplog.text.lower()


def test_naive_since_rejected():
    def handler(request):
        return httpx.Response(200, json=[])

    with pytest.raises(ValueError, match="must be timezone-aware"):
        _source(handler).collect_commits("o", "r", datetime(2026, 11, 25), UNTIL)


def test_transient_error_propagates_after_retries():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    with pytest.raises(TransientError):
        _source(handler).collect_commits("o", "r", SINCE, UNTIL)
    assert len(calls) == 3