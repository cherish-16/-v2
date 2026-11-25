from datetime import UTC, datetime

import pytest

from daily_report.collectors.mock import MockSourceBundle
from daily_report.models import AttendanceRecord

SINCE = datetime(2026, 11, 25, tzinfo=UTC)
UNTIL = datetime(2026, 11, 26, tzinfo=UTC)


def test_attendance_record_requires_source_id():
    with pytest.raises(ValueError, match="record_id"):
        AttendanceRecord(
            record_id="",
            member_open_id="ou_1",
            work_date=SINCE.date(),
            status="present",
            checked_in_at=SINCE,
            checked_out_at=SINCE,
        )


def test_attendance_record_normalizes_utc():
    record = AttendanceRecord(
        record_id="a1",
        member_open_id="ou_1",
        work_date=SINCE.date(),
        status="present",
        checked_in_at=datetime(2026, 11, 25, 9, tzinfo=UTC),
        checked_out_at=None,
    )
    assert record.checked_in_at.tzinfo is not None


def test_attendance_record_rejects_naive_time():
    with pytest.raises(ValueError, match="timezone-aware"):
        AttendanceRecord(
            record_id="a1",
            member_open_id="ou_1",
            work_date=SINCE.date(),
            status="present",
            checked_in_at=datetime(2026, 11, 25, 9),
            checked_out_at=None,
        )


def test_attendance_record_rejects_invalid_status():
    with pytest.raises(ValueError, match="status"):
        AttendanceRecord(
            record_id="a1",
            member_open_id="ou_1",
            work_date=SINCE.date(),
            status="sleeping",
            checked_in_at=None,
            checked_out_at=None,
        )


def test_mock_collects_attendance_in_window():
    record = AttendanceRecord(
        record_id="att-1",
        member_open_id="ou_1",
        work_date=SINCE.date(),
        status="present",
        checked_in_at=SINCE,
        checked_out_at=SINCE,
    )
    bundle = MockSourceBundle(attendance=[record])
    assert bundle.attendance_source.collect_attendance(SINCE, UNTIL) == [record]


def test_absence_record_supported():
    record = AttendanceRecord(
        record_id="att-2",
        member_open_id="ou_1",
        work_date=SINCE.date(),
        status="absent",
        checked_in_at=None,
        checked_out_at=None,
    )
    assert record.status == "absent"


def test_empty_window_returns_empty_list():
    assert MockSourceBundle().attendance_source.collect_attendance(UNTIL, UNTIL) == []


def test_naive_window_rejected():
    with pytest.raises(ValueError, match="must be timezone-aware"):
        MockSourceBundle().attendance_source.collect_attendance(
            datetime(2026, 11, 25),
            UNTIL,
        )