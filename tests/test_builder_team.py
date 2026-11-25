from datetime import UTC, date, datetime

from daily_report.generation.builder import generate_report
from daily_report.models import CommitRecord, Member, ReportScope

T = datetime(2026, 11, 25, 10, tzinfo=UTC)
DAY = date(2026, 11, 25)


def _members():
    return [
        Member(member_id="m1", name="张三", github_login="zhangsan"),
        Member(member_id="m2", name="李四", github_login="lisi"),
    ]


def _team(commits, members=None, **kwargs):
    return generate_report(
        scope=ReportScope.TEAM,
        entity_id="team-1",
        report_date=DAY,
        members=members or _members(),
        commits=commits,
        tasks=[],
        messages=[],
        **kwargs,
    )


def test_items_grouped_by_member_not_by_commit_count():
    commits = [
        CommitRecord(
            sha=f"z{i}", author_login="zhangsan", message="m", committed_at=T, repo="o/r"
        )
        for i in range(3)
    ] + [
        CommitRecord(sha="l1", author_login="lisi", message="m", committed_at=T, repo="o/r")
    ]
    report = _team(commits)
    texts = [i.text for i in report.items]
    assert sum(t.startswith("张三：") for t in texts) == 3
    assert sum(t.startswith("李四：") for t in texts) == 1


def test_member_without_data_still_listed_in_note():
    commits = [
        CommitRecord(
            sha="z1", author_login="zhangsan", message="m", committed_at=T, repo="o/r"
        )
    ]
    report = _team(commits)
    assert "李四" in report.note
    assert "无数据" in report.note


def test_missing_mapping_member_flagged():
    members = [
        Member(member_id="m1", name="张三", github_login="zhangsan"),
        Member(member_id="m2", name="王五"),
    ]
    report = _team([], members=members)
    assert "王五" in report.note
    assert "未配置映射" in report.note


def test_all_members_empty_returns_report_not_none():
    report = _team([])
    assert report is not None
    assert report.items == []
    assert "无数据" in report.note


def test_team_scope_recorded():
    report = _team([])
    assert report.scope is ReportScope.TEAM
    assert report.entity_id == "team-1"
    assert report.report_date == DAY