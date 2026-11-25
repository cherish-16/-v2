"""共享测试设施。

``close_connections`` 拦截 ``sqlite3.connect``，把测试期间创建的连接
在用例结束时统一关闭 —— 不关闭会触发 ResourceWarning，且在 Windows 上
会让临时目录清理失败。
"""

import sqlite3

import pytest

_TRACKED: list[sqlite3.Connection] = []


@pytest.fixture(autouse=True)
def close_connections(monkeypatch):
    tracked: list[sqlite3.Connection] = []
    original_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        tracked.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", tracking_connect)
    yield

    for conn in tracked:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 - 重复关闭不应让用例失败
            pass