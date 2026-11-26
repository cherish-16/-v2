"""从 specs/proposal.md §5 成功标准逐条导出的回归测试。

每条用例的编号对应 proposal 中的验收项，便于逐条核对。
"""

from datetime import UTC, date, datetime

import pytest

from daily_report.collectors.mock import MockSourceBundle
from daily_report.config import load_settings
from daily_report.models import (
    AttendanceRecord,
    CommitRecord,
    Member,
    ReportScope,
    TaskRecord,
)
from daily_report.orchestration.run_daily import PublisherBundle, run_daily
from daily_report.publishers.fake import FakePublisher
from daily_report.storage.repository import Repository
from daily_report.storage.schema import init_db

T = datetime(2026, 11, 25, 10, tzinfo=UTC)
DAY = date(2026, 11, 25)


@pytest.fixture
def env(tmp_path):
    repo = Repository(init_db(str(tmp_path / "reg.db")))
    repo.upsert_members(
        [
            Member(
                member_id="m1",
                name="张三",
                github_login="zhangsan",
                feishu_open_id="ou_1",
                email="a@test",
            )
        ]
    )
    sources = MockSourceBundle(
        commits=[
            CommitRecord(
                sha="s1", author_login="zhangsan", message="m", committed_at=T, repo="o/r"
            )
        ],
        tasks=[
            TaskRecord(
                task_id="t1", title="写文档", status="done", assignee_open_id="ou_1", updated_at=T
            )
        ],
        messages=[],
        attendance=[
            AttendanceRecord(
                record_id="att-1",
                member_open_id="ou_1",
                work_date=DAY,
                status="present",
                checked_in_at=T,
                checked_out_at=None,
            )
        ],
    )
    return repo, sources


def _run(repo, sources, **kwargs):
    return run_daily(
        "team-1",
        DAY,
        settings=load_settings({"GITHUB_OWNER": "o", "GITHUB_REPO": "r"}),
        repo=repo,
        sources=sources,
        publishers=PublisherBundle(email=FakePublisher()),
        now=T,
        **kwargs,
    )


def test_ac01_three_sources_collected(env):
    """AC-01 三源采集可用。"""
    repo, sources = env
    summary = _run(repo, sources)
    assert {"github", "feishu_task", "feishu_message"} <= set(summary.collected)


def test_ac02_personal_report_fully_traceable(env):
    """AC-02 个人日报条目可追溯率 100%。"""
    repo, sources = env
    _run(repo, sources)
    report = repo.get_report(ReportScope.PERSONAL, "m1", DAY)
    assert report.items
    assert all(item.source_id for item in report.items)


def test_ac03_team_report_grouped_and_formatted(env):
    """AC-03 团队日报按成员分组、格式统一。"""
    repo, sources = env
    _run(repo, sources)
    team = repo.get_report(ReportScope.TEAM, "team-1", DAY)
    assert team.items
    assert all("：" in item.text for item in team.items)


def test_ac04_email_sent(env):
    """AC-04 邮件推送返回结构化结果。"""
    repo, sources = env
    publisher = FakePublisher()
    run_daily(
        "team-1",
        DAY,
        settings=load_settings({"GITHUB_OWNER": "o", "GITHUB_REPO": "r"}),
        repo=repo,
        sources=sources,
        publishers=PublisherBundle(email=publisher),
        now=T,
    )
    assert publisher.email_calls
    assert publisher.email_calls[0][1] == ["a@test"]


def test_ac06_second_run_is_idempotent(env):
    """AC-06 同日重复触发被忽略。"""
    repo, sources = env
    _run(repo, sources)
    second = _run(repo, sources)
    assert second.status == "skipped"


def test_ac07_history_query(env):
    """AC-07 历史查询按日期区间返回。"""
    repo, sources = env
    _run(repo, sources)
    assert repo.list_reports(DAY, DAY)
    assert repo.list_reports(date(2026, 11, 26), date(2026, 11, 30)) == []


def test_ac08_no_secret_in_repository_config(env):
    """AC-08 密钥不进入配置对象的 repr。"""
    settings = load_settings({"GITHUB_TOKEN": "secret-value-xyz"})
    assert "secret-value-xyz" not in repr(settings)


def test_ac10_attendance_items_traceable(env):
    """AC-10 考勤条目可追溯。"""
    repo, sources = env
    _run(repo, sources)
    report = repo.get_report(ReportScope.PERSONAL, "m1", DAY)
    attendance = [i for i in report.items if i.source_type == "feishu_attendance"]
    assert attendance
    assert all(item.source_id == "att-1" for item in attendance)


def test_ac_e1_no_data_day_still_generates(env):
    """边界 AC-E1 全组无数据仍生成日报。"""
    repo, _ = env
    summary = _run(repo, MockSourceBundle())
    assert summary.status == "success"
    team = repo.get_report(ReportScope.TEAM, "team-1", DAY)
    assert team is not None
    assert "无数据" in team.note


def test_ac_e3_unmapped_member_not_guessed(tmp_path):
    """边界 AC-E3 未配置映射成员不猜测归属。"""
    repo = Repository(init_db(str(tmp_path / "e3.db")))
    repo.upsert_members([Member(member_id="m9", name="王五")])
    summary = _run(repo, MockSourceBundle())
    assert summary.status == "success"
    team = repo.get_report(ReportScope.TEAM, "team-1", DAY)
    assert "未配置映射" in team.note