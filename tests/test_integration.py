from datetime import UTC, date, datetime

from daily_report.collectors.mock import MockSourceBundle
from daily_report.config import load_settings
from daily_report.models import (
    CommitRecord,
    Member,
    MessageRecord,
    ReportScope,
    TaskRecord,
)
from daily_report.orchestration.run_daily import PublisherBundle, run_daily
from daily_report.publishers.fake import FakePublisher
from daily_report.storage.repository import Repository
from daily_report.storage.schema import init_db

T = datetime(2026, 11, 25, 10, tzinfo=UTC)
DAY = date(2026, 11, 25)


def test_full_pipeline_end_to_end(tmp_path):
    repo = Repository(init_db(str(tmp_path / "e2e.db")))
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
                sha="s1", author_login="zhangsan", message="改接口", committed_at=T, repo="o/r"
            )
        ],
        tasks=[
            TaskRecord(
                task_id="t1", title="写文档", status="done", assignee_open_id="ou_1", updated_at=T
            )
        ],
        messages=[
            MessageRecord(
                msg_id="om1", sender_open_id="ou_1", content="同步", created_at=T, chat_id="c1"
            )
        ],
    )
    publisher = FakePublisher()
    summary = run_daily(
        "team-1",
        DAY,
        settings=load_settings({"GITHUB_OWNER": "o", "GITHUB_REPO": "r"}),
        repo=repo,
        sources=sources,
        publishers=PublisherBundle(email=publisher),
        now=T,
    )
    assert summary.status == "success"
    personal = repo.get_report(ReportScope.PERSONAL, "m1", DAY)
    team = repo.get_report(ReportScope.TEAM, "team-1", DAY)
    assert len(personal.items) == 3
    assert all(item.source_id for item in personal.items)
    assert team.items
    assert publisher.email_calls


def test_pipeline_is_repeatable(tmp_path):
    repo = Repository(init_db(str(tmp_path / "r2.db")))
    repo.upsert_members([Member(member_id="m1", name="张三", github_login="zhangsan",
        feishu_open_id="ou_1")])
    sources = MockSourceBundle(
        commits=[
            CommitRecord(
                sha="s1", author_login="zhangsan", message="m", committed_at=T, repo="o/r"
            )
        ]
    )
    args = dict(
        settings=load_settings({"GITHUB_OWNER": "o", "GITHUB_REPO": "r"}),
        repo=repo,
        sources=sources,
        publishers=PublisherBundle(email=FakePublisher()),
        now=T,
    )
    run_daily("team-1", DAY, **args)
    before = len(repo.list_reports(DAY, DAY))
    run_daily("team-1", DAY, **args)
    assert len(repo.list_reports(DAY, DAY)) == before
