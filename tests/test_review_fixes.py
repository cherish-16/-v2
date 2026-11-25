"""代码复审发现缺陷的回归测试（Critical / Important 各条对应一个用例）。"""

from datetime import UTC, date, datetime

import pytest

from daily_report.collectors.base import SourceBundle
from daily_report.collectors.mock import MockSourceBundle
from daily_report.config import load_settings
from daily_report.errors import ConfigError
from daily_report.generation.attribution import attribute
from daily_report.generation.builder import generate_report
from daily_report.models import CommitRecord, Member, ReportScope
from daily_report.orchestration.run_daily import PublisherBundle, run_daily
from daily_report.publishers.base import SendResult
from daily_report.publishers.fake import FakePublisher
from daily_report.storage.repository import Repository
from daily_report.storage.schema import init_db

T = datetime(2026, 11, 25, 10, tzinfo=UTC)
DAY = date(2026, 11, 25)
REPO_ENV = {"GITHUB_OWNER": "o", "GITHUB_REPO": "r"}


class FailingCommitSource:
    def collect_commits(self, *args, **kwargs):
        raise RuntimeError("github down")


class FailingBot:
    def push_to_feishu(self, report, webhook=None):
        raise RuntimeError("bot exploded")


class FailingEmail:
    def __init__(self, addresses):
        self._addresses = addresses
        self.calls = 0

    def send_email(self, report, recipients):
        self.calls += 1
        return SendResult(success=[], failed=[(a, "boom") for a in recipients])


@pytest.fixture
def repo(tmp_path):
    conn = init_db(str(tmp_path / "r.db"))
    yield Repository(conn)
    conn.close()


def _run(repo, sources=None, publishers=None, **kwargs):
    return run_daily(
        "team-1",
        DAY,
        settings=kwargs.pop("settings", load_settings(REPO_ENV)),
        repo=repo,
        sources=sources or MockSourceBundle(),
        publishers=publishers or PublisherBundle(email=FakePublisher()),
        now=T,
        **kwargs,
    )


# ---------- C1：幂等要覆盖 partial，且不得重复发信 ----------


def test_c1_partial_run_is_not_repeated(repo):
    repo.upsert_members(
        [Member(member_id="m1", name="张三", github_login="z", email="a@test")]
    )
    mock = MockSourceBundle()
    sources = SourceBundle(FailingCommitSource(), mock.task_source, mock.message_source)
    publisher = FakePublisher()

    first = _run(repo, sources=sources, publishers=PublisherBundle(email=publisher))
    second = _run(repo, sources=sources, publishers=PublisherBundle(email=publisher))

    assert first.status == "partial"
    assert second.status == "skipped"
    assert len(publisher.email_calls) == 1


def test_c1_failed_rerun_does_not_overwrite_report(repo):
    repo.upsert_members([Member(member_id="m1", name="张三", github_login="z")])
    commits = [
        CommitRecord(sha="s1", author_login="z", message="真实提交", committed_at=T, repo="o/r")
    ]
    _run(repo, sources=MockSourceBundle(commits=commits))
    good = repo.get_report(ReportScope.TEAM, "team-1", DAY)
    assert len(good.items) == 1

    mock = MockSourceBundle()
    _run(
        repo,
        sources=SourceBundle(FailingCommitSource(), mock.task_source, mock.message_source),
    )
    after = repo.get_report(ReportScope.TEAM, "team-1", DAY)
    assert after is not None
    assert len(after.items) == 1, "降级数据不得覆盖已有的好日报"


# ---------- C2：空成员不得判 success ----------


def test_c2_empty_members_is_not_success(repo):
    summary = _run(repo)
    assert summary.status != "success"
    assert "members" in summary.failed or "members" in str(summary.failed)


def test_c2_fix_members_and_rerun_works(repo):
    _run(repo)
    repo.upsert_members([Member(member_id="m1", name="张三", github_login="z")])
    summary = _run(repo)
    assert summary.status in ("success", "partial")
    assert repo.get_report(ReportScope.PERSONAL, "m1", DAY) is not None


# ---------- C3：非法时区必须报错，不得静默回退 ----------


def test_c3_invalid_timezone_rejected():
    with pytest.raises(ConfigError, match="timezone|TIMEZONE"):
        load_settings({"DAILY_REPORT_TIMEZONE": "Asia/Shangai"})


# ---------- C4：半配置成员的提交必须被标注，而不是静默消失 ----------


def test_c4_half_configured_member_mapping_gap_reported():
    members = [
        Member(member_id="m1", name="张三", github_login="zhangsan"),
        Member(member_id="m2", name="李四", feishu_open_id="ou2"),
    ]
    commits = [
        CommitRecord(
            sha="s1", author_login="zhangsan", message="张三的", committed_at=T, repo="o/r"
        )
    ]
    result = attribute(members, commits, [], [])
    assert "m2" in result.mapping_gaps
    assert "github_login" in result.mapping_gaps["m2"]


def test_c4_half_configured_member_noted_in_team_report():
    members = [
        Member(member_id="m1", name="张三", github_login="zhangsan"),
        Member(member_id="m2", name="李四", feishu_open_id="ou2"),
    ]
    report = generate_report(
        ReportScope.TEAM, "team-1", DAY, members=members, commits=[], tasks=[], messages=[]
    )
    assert "未配置映射" in (report.note or "")
    assert "李四" in (report.note or "")


# ---------- I1：推送异常必须被隔离并记入摘要 ----------


def test_i1_email_config_error_is_isolated(repo):
    repo.upsert_members([Member(member_id="m1", name="张三", github_login="z", email="a@test")])

    class BrokenEmail:
        def send_email(self, report, recipients):
            raise ConfigError("SMTP configuration missing")

    summary = _run(repo, publishers=PublisherBundle(email=BrokenEmail()))
    assert summary.status in ("partial", "failed")
    assert any("email" in key for key in summary.failed)


def test_i1_bot_error_is_isolated(repo):
    repo.upsert_members(
        [Member(member_id="m1", name="张三", github_login="z", email="a@test")]
    )
    summary = _run(
        repo, publishers=PublisherBundle(email=FakePublisher(), bot=FailingBot())
    )
    assert "feishu_bot" in summary.failed


def test_i1_all_channels_failed_yields_failed_status(repo):
    repo.upsert_members(
        [Member(member_id="m1", name="张三", github_login="z", email="a@test")]
    )
    mock = MockSourceBundle()
    sources = SourceBundle(
        FailingCommitSource(), mock.task_source, mock.message_source
    )

    class BrokenEmail:
        def send_email(self, report, recipients):
            raise ConfigError("no smtp")

    summary = _run(
        repo,
        sources=sources,
        publishers=PublisherBundle(email=BrokenEmail(), bot=FailingBot()),
    )
    assert summary.status == "failed"


# ---------- I2：单成员生成失败不得拖垮整批 ----------


def test_i2_bad_record_does_not_abort_batch(repo):
    repo.upsert_members(
        [
            Member(member_id="m1", name="张三", github_login="z1"),
            Member(member_id="m2", name="李四", github_login="z2"),
        ]
    )

    class DirtySource:
        """返回一条空 sha 的提交 —— 生成层会抛 TraceabilityError。"""

        def collect_commits(self, *args, **kwargs):
            return [
                CommitRecord(sha="good", author_login="z1", message="ok", committed_at=T,
                    repo="o/r"),
                CommitRecord(sha="", author_login="z2", message="x", committed_at=T, repo="o/r"),
            ]

    summary = _run(repo, sources=SourceBundle(DirtySource(), *_fakes()))
    # 张三的日报必须成功生成，李四的失败只影响他自己
    assert repo.get_report(ReportScope.PERSONAL, "m1", DAY) is not None
    assert any("personal:m2" in key or "team_report" in key for key in summary.failed)
    assert summary.status in ("partial", "failed")


def _fakes():
    m = MockSourceBundle()
    return m.task_source, m.message_source


# ---------- I3：失败摘要不得含明文邮箱 ----------


def test_i3_failed_summary_masks_email(repo):
    repo.upsert_members(
        [Member(member_id="m1", name="张三", github_login="z", email="secret@corp.com")]
    )
    summary = _run(
        repo, publishers=PublisherBundle(email=FailingEmail(["secret@corp.com"]))
    )
    joined = str(summary.failed)
    assert "secret@corp.com" not in joined
    assert "s***@corp.com" in joined


# ---------- I4：飞书分页截断必须可感知 ----------

def test_i4_feishu_truncation_warns():
    import httpx

    from daily_report.collectors.feishu import FeishuTaskSource

    def handler(request):
        if "tenant_access_token" in str(request.url):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "t"})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "id": "t1",
                            "summary": "x",
                            "completed_at": "0",
                            "updated_at": str(int(T.timestamp() * 1000)),
                            "members": [],
                        }
                    ],
                    "has_more": True,
                },
            },
        )

    source = FeishuTaskSource(
        httpx.Client(transport=httpx.MockTransport(handler)), "id", "s"
    )
    import warnings as _w
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        result = source.collect_tasks(T, datetime(2026, 11, 26, tzinfo=UTC))
    assert result, "expected at least one record"
    assert caught, f"no warnings; result={len(result)}"


# ---------- I9：--date 默认值应取团队时区 ----------

def test_i9_default_date_uses_team_timezone():
    from daily_report.cli import resolve_default_date

    # 上海时间 2026-11-26 00:30 时，UTC 还是 11-25 16:30
    utc_now = datetime(2026, 11, 25, 16, 30, tzinfo=UTC)
    assert resolve_default_date("Asia/Shanghai", utc_now) == date(2026, 11, 26)
    assert resolve_default_date("UTC", utc_now) == date(2026, 11, 25)
