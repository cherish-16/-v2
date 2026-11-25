from datetime import UTC, date, datetime

import pytest

from daily_report.errors import TraceabilityError
from daily_report.generation.builder import generate_report
from daily_report.models import (
    CommitRecord,
    Member,
    MessageRecord,
    ReportScope,
    TaskRecord,
)

T = datetime(2026, 11, 25, 10, tzinfo=UTC)
DAY = date(2026, 11, 25)


def _member():
    return Member(
        member_id="m1", name="张三", github_login="zhangsan", feishu_open_id="ou_1"
    )


def _commits():
    return [
        CommitRecord(
            sha="s1", author_login="zhangsan", message="改接口", committed_at=T, repo="o/r"
        )
    ]


def _tasks():
    return [
        TaskRecord(
            task_id="t1", title="写文档", status="done", assignee_open_id="ou_1", updated_at=T
        )
    ]


def _messages():
    return [
        MessageRecord(
            msg_id="om1", sender_open_id="ou_1", content="同步进度", created_at=T, chat_id="c1"
        )
    ]


def _generate(**kwargs):
    params = dict(
        scope=ReportScope.PERSONAL,
        entity_id="m1",
        report_date=DAY,
        members=[_member()],
        commits=[],
        tasks=[],
        messages=[],
    )
    params.update(kwargs)
    return generate_report(**params)


def test_items_ordered_commits_tasks_messages():
    report = _generate(commits=_commits(), tasks=_tasks(), messages=_messages())
    assert [i.source_type for i in report.items] == [
        "github",
        "feishu_task",
        "feishu_message",
    ]


def test_every_item_is_traceable():
    report = _generate(commits=_commits(), tasks=_tasks(), messages=_messages())
    assert all(i.source_id for i in report.items)
    assert [i.source_id for i in report.items] == ["s1", "t1", "om1"]


def test_no_data_day_returns_report_with_note():
    report = _generate()
    assert report is not None
    assert report.items == []
    assert report.note == "无数据"


def test_missing_source_recorded_in_note():
    report = _generate(commits=_commits(), missing_sources=["feishu_message"])
    assert "来源缺失" in report.note
    assert "feishu_message" in report.note


def test_only_own_records_included():
    other = CommitRecord(
        sha="s9", author_login="lisi", message="别人的", committed_at=T, repo="o/r"
    )
    report = _generate(commits=_commits() + [other])
    assert [i.source_id for i in report.items] == ["s1"]


def test_scope_is_required():
    with pytest.raises(TypeError):
        generate_report(
            entity_id="m1", report_date=DAY, members=[], commits=[], tasks=[], messages=[]
        )


def test_empty_source_id_raises_traceability_error():
    bad = MessageRecord(
        msg_id="", sender_open_id="ou_1", content="x", created_at=T, chat_id="c1"
    )
    with pytest.raises(TraceabilityError):
        _generate(messages=[bad])