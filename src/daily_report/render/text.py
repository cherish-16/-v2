"""文本与 HTML 渲染。

三个函数都是纯函数：不修改入参、无 IO、不做数据加工 ——
内容怎么组织是生成层的事，这里只负责呈现。
"""

from __future__ import annotations

from html import escape

from daily_report.models import DailyReport, ReportItem, ReportScope

_SCOPE_TITLE = {
    ReportScope.PERSONAL: "个人日报",
    ReportScope.TEAM: "团队日报",
}


def _title(report: DailyReport) -> str:
    return f"{report.report_date.isoformat()} {_SCOPE_TITLE[report.scope]}"


def render_text(report: DailyReport) -> str:
    lines = [_title(report)]
    for item in report.items:
        lines.append(f"- [{item.source_type}] {item.text}")
    if report.note:
        lines.append(f"备注：{report.note}")
    return "\n".join(lines)


def render_email_html(report: DailyReport) -> str:
    rows = "".join(
        f"<li>[{escape(item.source_type)}] {escape(item.text)}</li>"
        for item in report.items
    )
    note = (
        f'<p class="note">备注：{escape(report.note)}</p>' if report.note else ""
    )
    return (
        "<html><body>"
        f"<h2>{escape(_title(report))}</h2>"
        f"<ul>{rows}</ul>"
        f"{note}"
        "</body></html>"
    )


def render_team_text(report: DailyReport) -> str:
    """按成员分组输出。

    条目文本形如「张三：改接口」，取第一个全角冒号前的内容作为成员名；
    切不出成员名的归入「其他」。
    """
    groups: dict[str, list[ReportItem]] = {}
    for item in report.items:
        name, sep, _ = item.text.partition("：")
        key = name if sep else "其他"
        groups.setdefault(key, []).append(item)

    lines = [_title(report)]
    for name, items in groups.items():
        lines.append(f"## {name}")
        for item in items:
            _, sep, body = item.text.partition("：")
            lines.append(f"- [{item.source_type}] {body if sep else item.text}")
    if report.note:
        lines.append(f"备注：{report.note}")
    return "\n".join(lines)