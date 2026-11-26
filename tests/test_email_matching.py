"""未关联 GitHub 账号的提交，按提交邮箱归属到成员。"""

from datetime import UTC, date, datetime

from daily_report.generation.attribution import attribute
from daily_report.generation.builder import generate_report
from daily_report.models import CommitRecord, Member, ReportScope

T = datetime(2026, 11, 25, 10, tzinfo=UTC)
DAY = date(2026, 11, 25)


def _commit(login=None, email=None, sha="s1"):
    return CommitRecord(
        sha=sha,
        author_login=login or "lvzhenyu(unmapped)",
        message="改接口",
        committed_at=T,
        repo="o/r",
        author_email=email,
    )


def test_commit_matched_by_author_email():
    """GitHub 未关联账号时 author_login 是 None，仍应按提交邮箱归到成员。"""
    member = Member(
        member_id="m1",
        name="吕振宇",
        github_login="tenacity123-beep",
        git_emails=("13894169122@163.com",),
    )
    result = attribute([member], [_commit(email="13894169122@163.com")], [], [])
    assert [c.sha for c in result.by_member["m1"].commits] == ["s1"]


def test_commit_email_match_is_case_insensitive():
    member = Member(member_id="m1", name="吕振宇", git_emails=("Me@Example.com",))
    result = attribute([member], [_commit(email="me@example.com")], [], [])
    assert result.by_member["m1"].commits


def test_unmatched_commit_still_dropped():
    member = Member(member_id="m1", name="吕振宇", git_emails=("a@x.com",))
    result = attribute([member], [_commit(email="other@y.com")], [], [])
    assert result.by_member["m1"].commits == []


def test_login_match_still_takes_priority():
    member = Member(
        member_id="m1", name="吕振宇",
        github_login="tenacity123-beep",
        git_emails=("a@x.com",),
    )
    result = attribute(
        [member], [_commit(login="tenacity123-beep", email="other@y.com")], [], []
    )
    assert result.by_member["m1"].commits


def test_report_contains_email_matched_commit():
    member = Member(
        member_id="m1", name="吕振宇", github_login="tenacity123-beep",
        git_emails=("13894169122@163.com",),
    )
    report = generate_report(
        ReportScope.TEAM, "t1", DAY, members=[member],
        commits=[_commit(email="13894169122@163.com")], tasks=[], messages=[],
    )
    assert len(report.items) == 1
    assert report.items[0].text.startswith("吕振宇：")
