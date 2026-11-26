"""异常类型与错误码。

本模块只定义类型，不含任何处理策略——如何处理是调用方的事。
"""

from __future__ import annotations


class ReportError(Exception):
    """全部业务异常的基类。"""

    code: str = "E-REPORT"


class ConfigError(ReportError):
    """配置缺失或非法（环境变量、必填项）。"""

    code = "E-CONFIG"


class AuthenticationError(ReportError):
    """外部系统认证失败。不可重试——重试只会放大无效请求。"""

    code = "E-AUTH"


class TransientError(ReportError):
    """瞬时故障（超时、限流、5xx）。可由调用方决定是否重试。"""

    code = "E-TRANSIENT"


class TraceabilityError(ReportError):
    """条目缺少来源标识，违反可追溯约束。"""

    code = "E-TRACE"