import copy
from datetime import UTC, date, datetime

from daily_report.models import DailyReport, ReportItem, ReportScope
from daily_report.render.text import render_email_html, render_team_text, render_text

T = datetime(2026, 11, 25, 10, tzinfo=UTC)


def _report(items, note=None, scope=ReportScope.PERSONAL):
    return DailyReport(
        scope=scope,
        entity_id="m1",
        report_date=date(2026, 11, 25),
        items=items,
        generated_at=T,
        note=note,
    )


def _items():
    return [
        ReportItem(source_type="github", source_id="s1", text="改接口", occurred_at=T),
        ReportItem(
            source_type="feishu_message", source_id="om1", text="<b>同步</b>", occurred_at=T
        ),
    ]


def test_text_contains_all_item_lines():
    text = render_text(_report(_items()))
    assert "改接口" in text
    assert "2026-11-25" in text


def test_text_marks_no_data():
    assert "无数据" in render_text(_report([], note="无数据"))


def test_html_escapes_special_characters():
    html = render_email_html(_report(_items()))
    assert "<b>同步</b>" not in html
    assert "&lt;b&gt;" in html


def test_render_does_not_mutate_input():
    report = _report(_items())
    snapshot = copy.deepcopy(report)
    render_text(report)
    render_email_html(report)
    render_team_text(report)
    assert report == snapshot


def test_team_render_groups_by_member_prefix():
    items = [
        ReportItem(source_type="github", source_id="s1", text="张三：改接口", occurred_at=T),
        ReportItem(source_type="github", source_id="s2", text="张三：写文档", occurred_at=T),
        ReportItem(source_type="github", source_id="s3", text="李四：修缺陷", occurred_at=T),
    ]
    text = render_team_text(_report(items, scope=ReportScope.TEAM))
    assert text.count("张三") >= 1
    assert "李四" in text