from datetime import UTC, date, datetime

import pytest

from daily_report.collectors.base import SourceBundle
from daily_report.collectors.mock import MockSourceBundle
from daily_report.config import load_settings
from daily_report.models import Member, ReportScope
from daily_report.orchestration.run_daily import PublisherBundle, run_daily
from daily_report.publishers.fake import FakePublisher
from daily_report.storage.repository import Repository
from daily_report.storage.schema import init_db

T = datetime(2026, 11, 25, 10, tzinfo=UTC)
DAY = date(2026, 11, 25)


class FailingSource:
    def collect_commits(self, owner, repo, since, until, *, max_pages=10):
        raise RuntimeError("github down")


@pytest.fixture
def repo(tmp_path):
    conn = init_db(str(tmp_path / "r.db"))
    repository = Repository(conn)
    repository.upsert_members(
        [Member(member_id="m1", name="张三", github_login="zhangsan",
                feishu_open_id="ou_1", email="a@test")]
    )
    yield repository
    conn.close()


def _run(repo, sources=None, publishers=None):
    return run_daily(
        "team-1",
        DAY,
        settings=load_settings({"GITHUB_OWNER": "o", "GITHUB_REPO": "r"}),
        repo=repo,
        sources=sources or MockSourceBundle(),
        publishers=publishers or PublisherBundle(email=FakePublisher()),
        now=T,
    )


def test_success_run_records_summary(repo):
    summary = _run(repo)
    assert summary.status == "success"
    assert repo.find_successful_run("team-1", DAY) is not None


def test_second_run_same_day_is_skipped(repo):
    _run(repo)
    after_first = len(repo.list_reports(DAY, DAY))
    summary = _run(repo)
    assert summary.status == "skipped"
    # 一次运行产出「每人一份个人日报 + 一份团队日报」，重复运行不得新增
    assert after_first == 2
    assert len(repo.list_reports(DAY, DAY)) == after_first


def test_single_source_failure_does_not_abort(repo):
    mock = MockSourceBundle()
    publishers = PublisherBundle(email=FakePublisher())
    summary = run_daily(
        "team-1",
        DAY,
        settings=load_settings({"GITHUB_OWNER": "o", "GITHUB_REPO": "r"}),
        repo=repo,
        sources=SourceBundle(
            FailingSource(), mock.task_source, mock.message_source
        ),
        publishers=publishers,
        now=T,
    )
    assert summary.status in ("success", "partial")
    assert "github" in str(summary.failed)


def test_push_failure_keeps_report(repo):
    """AC-E5：全部推送渠道失败 → 日报仍入库，摘要标记 failed。"""
    publishers = PublisherBundle(email=FakePublisher(fail_email=True))
    summary = _run(repo, publishers=publishers)
    assert summary.status == "failed"
    assert repo.get_report(ReportScope.TEAM, "team-1", DAY) is not None


def test_report_persisted_for_all_members(repo):
    _run(repo)
    assert repo.get_report(ReportScope.PERSONAL, "m1", DAY) is not None
    assert repo.get_report(ReportScope.TEAM, "team-1", DAY) is not None