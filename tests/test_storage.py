import sqlite3
from datetime import UTC, date, datetime

import pytest

from daily_report.models import CommitRecord, DailyReport, Member, ReportScope, RunSummary
from daily_report.storage.repository import Repository
from daily_report.storage.schema import init_db


@pytest.fixture
def repo(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    yield Repository(conn)
    conn.close()


def test_init_db_is_idempotent(tmp_path):
    path = str(tmp_path / "a.db")
    init_db(path).close()
    init_db(path).close()


def test_save_commits_deduplicates_by_sha(repo):
    record = CommitRecord(
        sha="abc",
        author_login="u",
        message="m",
        committed_at=datetime(2026, 11, 25, tzinfo=UTC),
        repo="o/r",
    )
    assert repo.save_commits([record]) == 1
    assert repo.save_commits([record]) == 0


def test_save_report_upserts_same_key(repo):
    report = DailyReport(
        scope=ReportScope.PERSONAL,
        entity_id="m1",
        report_date=date(2026, 11, 25),
        items=[],
        generated_at=datetime(2026, 11, 25, tzinfo=UTC),
    )
    repo.save_report(report)
    report.note = "无数据"
    repo.save_report(report)
    stored = repo.get_report(ReportScope.PERSONAL, "m1", date(2026, 11, 25))
    assert stored.note == "无数据"


def test_find_successful_run_ignores_failed_runs(repo):
    failed = RunSummary(
        team_id="t1",
        run_date=date(2026, 11, 25),
        status="failed",
        collected={},
        sent={},
        failed={},
        started_at=datetime(2026, 11, 25, tzinfo=UTC),
        finished_at=datetime(2026, 11, 25, tzinfo=UTC),
    )
    repo.save_run_summary(failed)
    assert repo.find_successful_run("t1", date(2026, 11, 25)) is None


def test_duplicate_successful_run_rejected(repo):
    summary = RunSummary(
        team_id="t1",
        run_date=date(2026, 11, 25),
        status="success",
        collected={},
        sent={},
        failed={},
        started_at=datetime(2026, 11, 25, tzinfo=UTC),
        finished_at=datetime(2026, 11, 25, tzinfo=UTC),
    )
    repo.save_run_summary(summary)
    with pytest.raises(sqlite3.IntegrityError):
        repo.save_run_summary(summary)


def test_list_reports_filters_by_date_range(repo):
    for day in (24, 25, 26):
        repo.save_report(
            DailyReport(
                scope=ReportScope.TEAM,
                entity_id="t1",
                report_date=date(2026, 11, day),
                items=[],
                generated_at=datetime(2026, 11, day, tzinfo=UTC),
            )
        )
    assert len(repo.list_reports(date(2026, 11, 25), date(2026, 11, 25))) == 1
    assert len(repo.list_reports(date(2026, 11, 1), date(2026, 11, 30))) == 3


def test_list_members_round_trips(repo):
    repo.upsert_members(
        [
            Member(member_id="m1", name="张三", github_login="zhangsan"),
            Member(member_id="m2", name="李四"),
        ]
    )
    members = repo.list_members()
    assert [m.member_id for m in members] == ["m1", "m2"]
    assert members[1].github_login is None