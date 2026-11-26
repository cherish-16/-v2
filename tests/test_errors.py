import pytest

from daily_report.errors import (
    AuthenticationError,
    ConfigError,
    ReportError,
    TraceabilityError,
    TransientError,
)


@pytest.mark.parametrize(
    ("cls", "code"),
    [
        (ConfigError, "E-CONFIG"),
        (AuthenticationError, "E-AUTH"),
        (TransientError, "E-TRANSIENT"),
        (TraceabilityError, "E-TRACE"),
    ],
)
def test_error_codes(cls, code):
    err = cls("boom")
    assert isinstance(err, ReportError)
    assert err.code == code
    assert str(err) == "boom"