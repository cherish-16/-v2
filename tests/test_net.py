import httpx
import pytest

from daily_report.errors import AuthenticationError, TransientError
from daily_report.net import get_json


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_returns_parsed_json():
    client = _client(lambda request: httpx.Response(200, json={"ok": True}))
    assert get_json(client, "https://api.test/x") == {"ok": True}


def test_401_raises_authentication_error_without_retry():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401)

    with pytest.raises(AuthenticationError):
        get_json(_client(handler), "https://api.test/x")
    assert len(calls) == 1


def test_500_is_retried_then_raises():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    with pytest.raises(TransientError):
        get_json(_client(handler), "https://api.test/x", sleep=lambda _: None)
    assert len(calls) == 3


def test_429_then_success_recovers():
    responses = [httpx.Response(429), httpx.Response(200, json={"ok": True})]

    def handler(request):
        return responses.pop(0)

    result = get_json(_client(handler), "https://api.test/x", sleep=lambda _: None)
    assert result == {"ok": True}


def test_timeout_is_retried_then_raises():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.TimeoutException("slow")

    with pytest.raises(TransientError):
        get_json(_client(handler), "https://api.test/x", sleep=lambda _: None)
    assert len(calls) == 3


def test_404_is_transient_without_retry():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(404)

    with pytest.raises(TransientError):
        get_json(_client(handler), "https://api.test/x", sleep=lambda _: None)
    assert len(calls) == 1