from datetime import UTC, date, datetime

from daily_report.generation.builder import generate_report
from daily_report.models import AttendanceRecord, Member, ReportScope

T = datetime(2026, 11, 25, 1, 12, tzinfo=UTC)
DAY = date(2026, 11, 25)


def _member():
    return Member(member_id="m1", name="张三", feishu_open_id="ou_1")


def _report(attendance):
    return generate_report(
        scope=ReportScope.PERSONAL,
        entity_id="m1",
        report_date=DAY,
        members=[_member()],
        commits=[],
        tasks=[],
        messages=[],
        attendance=attendance,
    )


def test_attendance_item_added_with_traceable_source():
    attendance = [
        AttendanceRecord(
            record_id="att-1",
            member_open_id="ou_1",
            work_date=DAY,
            status="present",
            checked_in_at=T,
            checked_out_at=None,
        )
    ]
    report = _report(attendance)
    assert len(report.items) == 1
    assert report.items[0].source_type == "feishu_attendance"
    assert report.items[0].source_id == "att-1"


def test_absence_marked_in_item_text():
    attendance = [
        AttendanceRecord(
            record_id="att-2",
            member_open_id="ou_1",
            work_date=DAY,
            status="absent",
            checked_in_at=None,
            checked_out_at=None,
        )
    ]
    report = _report(attendance)
    assert "缺勤" in report.items[0].text


def test_late_and_leave_rendered():
    late = AttendanceRecord(
        record_id="att-3",
        member_open_id="ou_1",
        work_date=DAY,
        status="late",
        checked_in_at=T,
        checked_out_at=None,
    )
    leave = AttendanceRecord(
        record_id="att-4",
        member_open_id="ou_1",
        work_date=DAY,
        status="leave",
        checked_in_at=None,
        checked_out_at=None,
    )
    report = _report([late, leave])
    texts = [i.text for i in report.items]
    assert any("迟到" in t for t in texts)
    assert any("请假" in t for t in texts)


def test_no_attendance_keeps_backward_compatible_behavior():
    """没有考勤数据时，行为与引入考勤前一致（仍是「无数据」）。"""
    member = Member(
        member_id="m1", name="张三", github_login="zhangsan", feishu_open_id="ou_1"
    )
    report = generate_report(
        scope=ReportScope.PERSONAL,
        entity_id="m1",
        report_date=DAY,
        members=[member],
        commits=[],
        tasks=[],
        messages=[],
    )
    assert report.items == []
    assert report.note == "无数据"


def test_team_report_includes_attendance():
    attendance = [
        AttendanceRecord(
            record_id="att-9",
            member_open_id="ou_1",
            work_date=DAY,
            status="present",
            checked_in_at=T,
            checked_out_at=None,
        )
    ]
    report = generate_report(
        scope=ReportScope.TEAM,
        entity_id="team-1",
        report_date=DAY,
        members=[_member()],
        commits=[],
        tasks=[],
        messages=[],
        attendance=attendance,
    )
    assert len(report.items) == 1
    assert report.items[0].text.startswith("张三：")
    assert report.items[0].source_id == "att-9"