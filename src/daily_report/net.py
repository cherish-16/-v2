"""HTTP 调用的统一超时与重试（ADR-003）。

策略：按异常类型分流。认证失败不重试（重试只会放大无效请求）；
瞬时故障退避重试；其它 4xx 视为瞬时但不重试 —— 重试同样的请求不会有
不同结果。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from daily_report.errors import AuthenticationError, TransientError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0
_BACKOFF_SECONDS = (1.0, 2.0)


def _classify(status: int) -> str:
    """把 HTTP 状态码分为三种处置：认证失败 / 可重试 / 不可重试的瞬时故障。"""
    if status in (401, 403):
        return "auth"
    if status == 429 or 500 <= status < 600:
        return "retry"
    return "fail"


def _request_with_retry(
    call: Callable[[], httpx.Response],
    *,
    retry_times: int,
    sleep: Callable[[float], None],
) -> httpx.Response:
    """执行一次请求，按分类决定是否重试。返回最终成功的响应。"""
    attempt = 0
    last_error: str | None = None
    while True:
        try:
            response = call()
        except httpx.TimeoutException as exc:
            last_error = f"timeout: {exc}"
        except httpx.HTTPError as exc:
            last_error = f"transport error: {exc}"
        else:
            kind = _classify(response.status_code)
            if kind == "auth":
                raise AuthenticationError(
                    f"authentication failed with status {response.status_code}"
                )
            if response.status_code < 400:
                return response
            if kind == "fail":
                raise TransientError(
                    f"request failed with status {response.status_code}"
                )
            last_error = f"status {response.status_code}"

        if attempt >= retry_times:
            raise TransientError(f"request failed after {attempt + 1} attempts: {last_error}")
        delay = _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]
        logger.warning("retrying request in %.0fs after %s", delay, last_error)
        sleep(delay)
        attempt += 1


def _headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    return dict(headers) if headers else {}


def get_json(
    client: httpx.Client,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    retry_times: int = 2,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """GET 并解析 JSON。失败语义见模块文档。"""
    response = _request_with_retry(
        lambda: client.get(
            url, params=params, headers=_headers(headers), timeout=DEFAULT_TIMEOUT
        ),
        retry_times=retry_times,
        sleep=sleep,
    )
    return response.json()


def post_json(
    client: httpx.Client,
    url: str,
    *,
    json_body: Any,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    retry_times: int = 2,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """POST 并解析 JSON。失败语义同 :func:`get_json`。"""
    response = _request_with_retry(
        lambda: client.post(
            url,
            params=params,
            json=json_body,
            headers=_headers(headers),
            timeout=DEFAULT_TIMEOUT,
        ),
        retry_times=retry_times,
        sleep=sleep,
    )
    return response.json()