from datetime import UTC, datetime

import httpx
import pytest

from daily_report.collectors.feishu import FeishuMessageSource, FeishuTaskSource

SINCE = datetime(2026, 11, 25, tzinfo=UTC)
UNTIL = datetime(2026, 11, 26, tzinfo=UTC)


def _handler(routes):
    def handler(request):
        for prefix, response in routes.items():
            if prefix in str(request.url):
                return response
        return httpx.Response(404)

    return handler


def _token_response():
    return httpx.Response(
        200,
        json={
            "code": 0,
            "tenant_access_token": "t-123",
            "expire": 7200,
        },
    )


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_collect_tasks_maps_fields():
    body = {
        "code": 0,
        "data": {
            "items": [
                {
                    "id": "task-1",
                    "summary": "写接口",
                    "completed_at": "0",
                    "updated_at": "1795600800000",
                    "members": [{"id": "ou_1", "role": "assignee"}],
                }
            ],
            "has_more": False,
        },
    }

    source = FeishuTaskSource(
        _client(
            _handler(
                {
                    "open-apis/auth/v3/tenant_access_token/internal": _token_response(),
                    "open-apis/task/v2/tasks": httpx.Response(200, json=body),
                }
            )
        ),
        app_id="cli_x",
        app_secret="s",
    )
    result = source.collect_tasks(SINCE, UNTIL)
    assert len(result) == 1
    assert result[0].task_id == "task-1"
    assert result[0].title == "写接口"
    assert result[0].assignee_open_id == "ou_1"
    assert result[0].updated_at.tzinfo is not None


def test_collect_messages_marks_recalled():
    body = {
        "code": 0,
        "data": {
            "items": [
                {
                    "message_id": "om_1",
                    "msg_type": "text",
                    "body": {"content": '{"text":"已撤回的消息"}'},
                    "sender": {"id": "ou_1"},
                    "create_time": "1795600800000",
                    "deleted": True,
                }
            ],
            "has_more": False,
        },
    }

    source = FeishuMessageSource(
        _client(
            _handler(
                {
                    "open-apis/auth/v3/tenant_access_token/internal": _token_response(),
                    "open-apis/im/v1/messages": httpx.Response(200, json=body),
                }
            )
        ),
        app_id="cli_x",
        app_secret="s",
    )
    result = source.collect_messages(SINCE, UNTIL)
    assert len(result) == 1
    assert result[0].is_recalled is True
    assert result[0].content == "已撤回的消息"


def test_empty_window_returns_empty_list():
    body = {"code": 0, "data": {"items": [], "has_more": False}}
    source = FeishuTaskSource(
        _client(
            _handler(
                {
                    "tenant_access_token": _token_response(),
                    "open-apis/task/v2/tasks": httpx.Response(200, json=body),
                }
            )
        ),
        app_id="cli_x",
        app_secret="s",
    )
    assert source.collect_tasks(UNTIL, UNTIL) == []


def test_naive_window_rejected():
    source = FeishuTaskSource(_client(lambda r: httpx.Response(200)), "a", "b")
    with pytest.raises(ValueError, match="must be timezone-aware"):
        source.collect_tasks(datetime(2026, 11, 25), UNTIL)


def test_access_token_fetched_once_per_instance():
    token_calls = []

    def handler(request):
        if "tenant_access_token" in str(request.url):
            token_calls.append(request)
            return _token_response()
        return httpx.Response(200, json={"code": 0, "data": {"items": [], "has_more": False}})

    source = FeishuTaskSource(_client(handler), app_id="cli_x", app_secret="s")
    source.collect_tasks(SINCE, UNTIL)
    source.collect_tasks(SINCE, UNTIL)
    assert len(token_calls) == 1