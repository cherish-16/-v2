# 智能日报生成器 v2 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从零实现智能日报生成器 v2——采集 GitHub 提交与飞书任务/消息，自动生成个人与团队日报，经邮件与飞书机器人推送，并以 SQLite 留存历史。

**Architecture:** 四层结构（采集 / 生成 / 推送 / 主编排），下层只依赖共享基础层，仅编排层可跨层调用。数据源与推送渠道以 `Protocol` 定义端口，真实实现与 Mock 实现共享同一契约，由配置切换。

**Tech Stack:** Python 3.12+、uv、httpx、标准库 `sqlite3`、pytest、ruff

**Spec:** `specs/proposal.md`、`specs/design.md`、`specs/tasks.md`

## Global Constraints

- Python 3.12+；依赖管理用 `uv`。
- HTTP 一律 `httpx`，显式 `timeout`。
- 存储一律标准库 `sqlite3`，**全部 SQL 参数化**，禁止字符串拼接。
- 所有时间参数必须为 **UTC aware**；`since` 含、`until` 不含；naive datetime 抛 `ValueError`。
- `generate_report` 的 `scope` 参数**必填、无默认值**。
- 无数据日返回带 `note="无数据"` 的日报，**绝不返回 `None`**。
- 凭证只从环境变量读取，任何代码、测试、文档中不得出现真实令牌。
- 日志中邮箱脱敏为 `a***@example.com`，令牌一律替换为 `***`。
- 提交信息格式：`feat|fix|test|docs|chore: [任务编号] 一句话说明`。
- 每个任务 = 一次提交；`ruff check .` 必须零告警。

## Review Focus

按"最可能让使用者踩坑"排序。每条都在所属任务中有对应测试。

1. **时区混用**——调用方传入本地时间或 naive datetime 时，跨零点会重复或漏采当天数据。期望：入口即拒绝，不静默按本地时区解释。
2. **无数据成员的静默消失**——某人当日无提交时，团队日报里该人整个消失，主编以为他没上班。期望：显式标注，绝不静默省略。
3. **映射缺失时的猜测归属**——成员没配 GitHub 账号时，按名字相似度猜一个，把别人的提交写进他的日报。期望：跳过并标注"未配置映射"，绝不猜测。
4. **同一天重复运行产生重复日报**——定时任务重触发或手动补跑，收件人一天收到两份。期望：第二次直接返回已有摘要并入库为 skipped。
5. **分页截断无声无息**——超过 `max_pages` 时静默返回部分数据，日报看起来完整实则缺条目。期望：记录 warning 且可被调用方感知。

---

## 文件结构

```text
pyproject.toml                      工程与工具链配置
.env.example                        环境变量清单（无真实值）
src/daily_report/
├── __init__.py
├── __main__.py                     python -m daily_report 入口
├── cli.py                          命令行参数与退出码
├── config.py                       Settings 与环境变量装配
├── errors.py                       异常类型与错误码
├── models.py                       领域数据结构
├── net.py                          httpx 超时与重试（ADR-003）
├── collectors/
│   ├── __init__.py
│   ├── base.py                     端口 Protocol 与 SourceBundle
│   ├── github.py                   GitHub REST 实现
│   ├── feishu.py                   飞书任务/消息/考勤实现
│   └── mock.py                     离线数据源
├── generation/
│   ├── __init__.py
│   ├── attribution.py              原始记录 → 成员归组
│   └── builder.py                  DailyReport 构建
├── render/
│   ├── __init__.py
│   └── text.py                     文本 / HTML 渲染
├── publishers/
│   ├── __init__.py
│   ├── base.py                     Publisher Protocol 与结果类型
│   ├── email.py                    SMTP 实现
│   ├── feishu_bot.py               webhook 实现
│   └── fake.py                     测试与演示用
├── storage/
│   ├── __init__.py
│   ├── schema.py                   建表 DDL
│   └── repository.py               全部 SQL 的唯一所在地
└── orchestration/
    ├── __init__.py
    └── run_daily.py                幂等编排
tests/                              与源文件一一对应
scripts/check_spec_drift.py         规范守护脚本（第 4 周）
```

---

## Task 1: 工程骨架、领域模型与异常

**Files:**
- Create: `pyproject.toml`, `.env.example`, `src/daily_report/__init__.py`, `src/daily_report/models.py`, `src/daily_report/errors.py`
- Test: `tests/test_models.py`, `tests/test_errors.py`

**Interfaces:**
- Produces:
  - `models.ReportScope`（`str, Enum`：`PERSONAL="personal"`, `TEAM="team"`）
  - `models.Member(member_id, name, github_login=None, feishu_open_id=None, email=None)`
  - `models.CommitRecord(sha, author_login, message, committed_at, repo)`
  - `models.TaskRecord(task_id, title, status, assignee_open_id, updated_at)`
  - `models.MessageRecord(msg_id, sender_open_id, content, created_at, chat_id, is_recalled=False)`
  - `models.ReportItem(source_type, source_id, text, occurred_at)`
  - `models.DailyReport(scope, entity_id, report_date, items, generated_at, note=None)`
  - `models.RunSummary(team_id, run_date, status, collected, sent, failed, started_at, finished_at)`
  - `models.ensure_utc(value: datetime) -> datetime`  —— naive 抛 `ValueError`
  - `errors.ReportError`（基类，含 `code` 属性）及其子类 `ConfigError`, `AuthenticationError`, `TransientError`, `TraceabilityError`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_models.py
import pytest
from datetime import datetime, timezone

from daily_report.models import (
    CommitRecord, DailyReport, ReportItem, ReportScope, ensure_utc,
)


def test_ensure_utc_rejects_naive_datetime():
    with pytest.raises(ValueError, match="must be timezone-aware"):
        ensure_utc(datetime(2026, 11, 25, 10, 0))


def test_ensure_utc_converts_to_utc():
    result = ensure_utc(datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc))
    assert result.tzinfo == timezone.utc


def test_commit_record_rejects_naive_committed_at():
    with pytest.raises(ValueError, match="must be timezone-aware"):
        CommitRecord(
            sha="a1", author_login="u", message="m",
            committed_at=datetime(2026, 11, 25), repo="o/r",
        )


def test_daily_report_note_is_none_by_default():
    report = DailyReport(
        scope=ReportScope.PERSONAL, entity_id="m1",
        report_date=datetime(2026, 11, 25).date(), items=[],
        generated_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
    )
    assert report.note is None


def test_report_item_requires_non_empty_source_id():
    with pytest.raises(ValueError, match="source_id"):
        ReportItem(
            source_type="github", source_id="", text="t",
            occurred_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
        )
```

```python
# tests/test_errors.py
import pytest
from daily_report.errors import (
    AuthenticationError, ConfigError, ReportError, TraceabilityError, TransientError,
)


@pytest.mark.parametrize(
    ("cls", "code"),
    [
        (ConfigError, "E-CONFIG"),
        (AuthenticationError, "E-AUTH"),
        (TransientError, "E-TRANSIENT"),
        (TraceabilityError, "E-TRACE"),
    ],
)
def test_error_codes(cls, code):
    err = cls("boom")
    assert isinstance(err, ReportError)
    assert err.code == code
    assert str(err) == "boom"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_models.py tests/test_errors.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'daily_report'`

- [ ] **Step 3: 实现**

`pyproject.toml`：`requires-python = ">=3.12"`；依赖 `httpx>=0.27`；dev 依赖 `pytest>=8`, `pytest-cov`, `ruff`；`[tool.pytest.ini_options] testpaths=["tests"]`；`[tool.ruff] line-length=100`, `target-version="py312"`；`[tool.ruff.lint] select=["E","F","I","UP","B"]`；`[build-system]` 用 hatchling，`[tool.hatch.build.targets.wheel] packages=["src/daily_report"]`。

`models.py`：全部 `@dataclass(frozen=True)`，`DailyReport`/`RunSummary` 为可变 `@dataclass`。所有 `datetime` 字段在 `__post_init__` 中调用 `ensure_utc` 归一。`ReportItem.__post_init__` 额外校验 `source_id` 非空。`RunSummary.status` 取 `"success" | "skipped" | "partial" | "failed"`。

`errors.py`：基类 `ReportError(Exception)`，类属性 `code: str = "E-REPORT"`，子类覆写 `code`。

`.env.example` 列出全部变量名与占位值（`GITHUB_TOKEN=`、`FEISHU_APP_ID=`、`FEISHU_APP_SECRET=`、`SMTP_HOST=`、`SMTP_PORT=`、`SMTP_USER=`、`SMTP_PASSWORD=`、`FEISHU_BOT_WEBHOOK=`、`DAILY_REPORT_SOURCE_MODE=mock`、`DAILY_REPORT_TIMEZONE=Asia/Shanghai`），每行上方注释说明用途。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_models.py tests/test_errors.py -v`
Expected: 9 passed

- [ ] **Step 5: 提交**

```bash
git add pyproject.toml .env.example src/daily_report/ tests/
git commit -m "feat: [T3-01][T3-02] 工程骨架、领域模型与异常体系"
```

---

## Task 2: 配置装配

**Files:**
- Create: `src/daily_report/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `errors.ConfigError`
- Produces:
  - `config.Settings`（`@dataclass(frozen=True)`）：`source_mode: str`（`"mock"|"live"`）、`timezone: str`、`github_token: str|None`、`feishu_app_id: str|None`、`feishu_app_secret: str|None`、`smtp_host: str|None`、`smtp_port: int`、`smtp_user: str|None`、`smtp_password: str|None`、`feishu_bot_webhook: str|None`、`max_pages: int = 10`、`retry_times: int = 2`
  - `config.load_settings(env: Mapping[str, str] | None = None) -> Settings` —— `env` 默认读 `os.environ`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_config.py
import pytest
from daily_report.config import load_settings
from daily_report.errors import ConfigError


def test_defaults_to_mock_mode():
    settings = load_settings({})
    assert settings.source_mode == "mock"
    assert settings.max_pages == 10
    assert settings.retry_times == 2


def test_live_mode_requires_github_token():
    with pytest.raises(ConfigError, match="GITHUB_TOKEN"):
        load_settings({"DAILY_REPORT_SOURCE_MODE": "live"})


def test_live_mode_accepts_complete_config():
    settings = load_settings({
        "DAILY_REPORT_SOURCE_MODE": "live",
        "GITHUB_TOKEN": "t0ken",
        "FEISHU_APP_ID": "cli_x",
        "FEISHU_APP_SECRET": "secret",
    })
    assert settings.source_mode == "live"
    assert settings.github_token == "t0ken"


def test_invalid_source_mode_rejected():
    with pytest.raises(ConfigError, match="source_mode"):
        load_settings({"DAILY_REPORT_SOURCE_MODE": "staging"})


def test_settings_repr_does_not_leak_secrets():
    settings = load_settings({"GITHUB_TOKEN": "super-secret-value"})
    assert "super-secret-value" not in repr(settings)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL —— `ImportError: cannot import name 'load_settings'`

- [ ] **Step 3: 实现**

`Settings` 用 `dataclasses.field(repr=False)` 标记 `github_token`、`feishu_app_secret`、`smtp_password`，使 `repr` 不泄露。`load_settings` 从 `env` 读取；`source_mode` 只接受 `mock`/`live`，其它值抛 `ConfigError`；`live` 模式下 `github_token` 缺失抛 `ConfigError`，消息中包含变量名。`smtp_port` 解析失败抛 `ConfigError`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_config.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add src/daily_report/config.py tests/test_config.py
git commit -m "feat: [T3-03] 环境变量配置装配与密钥脱敏"
```

---

## Task 3: 存储结构与仓储

**Files:**
- Create: `src/daily_report/storage/__init__.py`, `storage/schema.py`, `storage/repository.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Consumes: `models.*`
- Produces:
  - `storage.schema.init_db(path: str) -> sqlite3.Connection` —— 建表幂等，开 `foreign_keys` 与 WAL
  - `storage.repository.Repository(conn)`
    - `upsert_members(members: Sequence[Member]) -> None`
    - `list_members() -> list[Member]`
    - `save_commits(records: Sequence[CommitRecord]) -> int`（返回新增行数）
    - `save_tasks(records: Sequence[TaskRecord]) -> int`
    - `save_messages(records: Sequence[MessageRecord]) -> int`
    - `save_report(report: DailyReport) -> None`
    - `get_report(scope: ReportScope, entity_id: str, report_date: date) -> DailyReport | None`
    - `list_reports(since: date, until: date) -> list[DailyReport]`
    - `save_run_summary(summary: RunSummary) -> None`
    - `find_successful_run(team_id: str, run_date: date) -> RunSummary | None`
    
- [ ] **Step 1: 写失败的测试**

```python
# tests/test_storage.py
from datetime import date, datetime, timezone

import pytest

from daily_report.models import (
    CommitRecord, DailyReport, Member, ReportScope, RunSummary,
)
from daily_report.storage.repository import Repository
from daily_report.storage.schema import init_db

UTC = timezone.utc


@pytest.fixture
def repo(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    return Repository(conn)


def test_init_db_is_idempotent(tmp_path):
    path = str(tmp_path / "a.db")
    init_db(path).close()
    init_db(path).close()


def test_save_commits_deduplicates_by_sha(repo):
    record = CommitRecord(
        sha="abc", author_login="u", message="m",
        committed_at=datetime(2026, 11, 25, tzinfo=UTC), repo="o/r",
    )
    assert repo.save_commits([record]) == 1
    assert repo.save_commits([record]) == 0


def test_save_report_upserts_same_key(repo):
    report = DailyReport(
        scope=ReportScope.PERSONAL, entity_id="m1", report_date=date(2026, 11, 25),
        items=[], generated_at=datetime(2026, 11, 25, tzinfo=UTC),
    )
    repo.save_report(report)
    report.note = "无数据"
    repo.save_report(report)
    stored = repo.get_report(ReportScope.PERSONAL, "m1", date(2026, 11, 25))
    assert stored.note == "无数据"


def test_find_successful_run_ignores_failed_runs(repo):
    failed = RunSummary(
        team_id="t1", run_date=date(2026, 11, 25), status="failed",
        collected={}, sent={}, failed={},
        started_at=datetime(2026, 11, 25, tzinfo=UTC),
        finished_at=datetime(2026, 11, 25, tzinfo=UTC),
    )
    repo.save_run_summary(failed)
    assert repo.find_successful_run("t1", date(2026, 11, 25)) is None


def test_duplicate_successful_run_rejected(repo):
    summary = RunSummary(
        team_id="t1", run_date=date(2026, 11, 25), status="success",
        collected={}, sent={}, failed={},
        started_at=datetime(2026, 11, 25, tzinfo=UTC),
        finished_at=datetime(2026, 11, 25, tzinfo=UTC),
    )
    repo.save_run_summary(summary)
    with pytest.raises(Exception):
        repo.save_run_summary(summary)


def test_list_reports_filters_by_date_range(repo):
    for day in (24, 25, 26):
        repo.save_report(DailyReport(
            scope=ReportScope.TEAM, entity_id="t1", report_date=date(2026, 11, day),
            items=[], generated_at=datetime(2026, 11, day, tzinfo=UTC),
        ))
    assert len(repo.list_reports(date(2026, 11, 25), date(2026, 11, 25))) == 1
    assert len(repo.list_reports(date(2026, 11, 1), date(2026, 11, 30))) == 3


def test_list_members_round_trips(repo):
    repo.upsert_members([
        Member(member_id="m1", name="张三", github_login="zhangsan"),
        Member(member_id="m2", name="李四"),
    ])
    members = repo.list_members()
    assert [m.member_id for m in members] == ["m1", "m2"]
    assert members[1].github_login is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_storage.py -v`
Expected: FAIL —— `ImportError: cannot import name 'init_db'`

- [ ] **Step 3: 实现**

`schema.py`：`init_db` 用 `sqlite3.connect(path)`，执行 `PRAGMA foreign_keys=ON` 与 `PRAGMA journal_mode=WAL`，然后 `executescript` 建六张表（DDL 见 `design.md` §2.2），全部 `CREATE TABLE IF NOT EXISTS`。`daily_reports` 上 `UNIQUE(scope, entity_id, report_date)`；`run_summaries` 上 `CREATE UNIQUE INDEX ... ON run_summaries(team_id, run_date) WHERE status='success'`（部分索引实现"成功运行唯一"，失败与跳过可多条）。

`repository.py`：所有语句参数化（`?` 占位）。原始记录用 `INSERT OR IGNORE`，返回 `cursor.rowcount`。`save_report` 用 `INSERT ... ON CONFLICT(scope, entity_id, report_date) DO UPDATE SET body_json=excluded.body_json, note=excluded.note`。`DailyReport` 与 `issue_json` 之间用 `dataclasses.asdict` + `json.dumps(..., ensure_ascii=False, default=_datetime_iso)` 序列化，读取时反序列化回 `DailyReport`。`list_unmapped_members` 判断 `github_login` 或 `feishu_open_id` 至少一项为空。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_storage.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add src/daily_report/storage/ tests/test_storage.py
git commit -m "feat: [T3-04] SQLite 表结构与参数化仓储层"
```

---

## Task 5: 网络助手（ADR-003 重试分流）

**Files:**
- Create: `src/daily_report/net.py`
- Test: `tests/test_net.py`

**Interfaces:**
- Consumes: `errors.AuthenticationError`, `errors.TransientError`
- Produces:
  - `net.get_json(client: httpx.Client, url: str, *, params: dict | None = None, headers: dict | None = None, retry_times: int = 2, sleep: Callable[[float], None] = time.sleep) -> dict`
  - 行为：401/403 → `AuthenticationError` 不重试；429/5xx/超时 → 重试 `retry_times` 次后 `TransientError`；其它 4xx → `TransientError` 不重试

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_net.py
import httpx
import pytest

from daily_report.errors import AuthenticationError, TransientError
from daily_report.net import get_json


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_returns_parsed_json():
    client = _client(lambda request: httpx.Response(200, json={"ok": True}))
    assert get_json(client, "https://api.test/x") == {"ok": True}


def test_401_raises_authentication_error_without_retry():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401)

    with pytest.raises(AuthenticationError):
        get_json(_client(handler), "https://api.test/x")
    assert len(calls) == 1


def test_500_is_retried_then_raises():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    with pytest.raises(TransientError):
        get_json(_client(handler), "https://api.test/x", sleep=lambda _: None)
    assert len(calls) == 3


def test_429_then_success_recovers():
    responses = [httpx.Response(429), httpx.Response(200, json={"ok": True})]

    def handler(request):
        return responses.pop(0)

    result = get_json(_client(handler), "https://api.test/x", sleep=lambda _: None)
    assert result == {"ok": True}


def test_timeout_is_retried_then_raises():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.TimeoutException("slow")

    with pytest.raises(TransientError):
        get_json(_client(handler), "https://api.test/x", sleep=lambda _: None)
    assert len(calls) == 3


def test_404_is_transient_without_retry():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(404)

    with pytest.raises(TransientError):
        get_json(_client(handler), "https://api.test/x", sleep=lambda _: None)
    assert len(calls) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_net.py -v`
Expected: FAIL —— `ImportError: cannot import name 'get_json'`

- [ ] **Step 3: 实现**

退避为指数序列 `[1, 2]` 秒，通过注入的 `sleep` 调用（便于测试）。重试分类集中在一个 `_classify(status) -> str` 函数里返回 `"auth" | "retry" | "fail"`。`sleep` 参数默认 `time.sleep`，测试传入空函数。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_net.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add src/daily_report/net.py tests/test_net.py
git commit -m "feat: [T3-05] httpx 统一超时与按异常类型分流的重试"
```

---

## Task 6: 采集端口与 Mock 数据源

**Files:**
- Create: `src/daily_report/collectors/__init__.py`, `collectors/base.py`, `collectors/mock.py`
- Test: `tests/test_collectors_base.py`

**Interfaces:**
- Consumes: `models.*`
- Produces:
  - `collectors.base.CommitSource`、`TaskSource`、`MessageSource`（`Protocol`）
  - `collectors.base.SourceBundle`（`@dataclass`：`commit_source: CommitSource`、`task_source: TaskSource`、`message_source: MessageSource`）
  - `collectors.mock.MockSourceBundle()` —— 返回实现三个 Protocol 的实例，内部持有固定演示数据，支持构造时注入 `commits` / `tasks` / `messages` 列表

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_collectors_base.py
from datetime import datetime, timezone

import pytest

from daily_report.collectors.base import CommitSource, SourceBundle
from daily_report.collectors.mock import MockSourceBundle
from daily_report.models import CommitRecord

UTC = timezone.utc
SINCE = datetime(2026, 11, 25, tzinfo=UTC)
UNTIL = datetime(2026, 11, 26, tzinfo=UTC)


def test_mock_satisfies_protocols():
    bundle = MockSourceBundle()
    assert isinstance(bundle, SourceBundle)
    assert isinstance(bundle.commit_source, CommitSource)


def test_mock_returns_injected_commits():
    record = CommitRecord(
        sha="s1", author_login="u", message="m",
        committed_at=datetime(2026, 11, 25, 10, tzinfo=UTC), repo="o/r",
    )
    bundle = MockSourceBundle(commits=[record])
    result = bundle.commit_source.collect_commits("o", "r", SINCE, UNTIL)
    assert result == [record]


def test_mock_filters_by_time_window():
    before = CommitRecord(
        sha="old", author_login="u", message="m",
        committed_at=datetime(2026, 11, 24, 10, tzinfo=UTC), repo="o/r",
    )
    bundle = MockSourceBundle(commits=[before])
    assert bundle.commit_source.collect_commits("o", "r", SINCE, UNTIL) == []


def test_naive_datetime_rejected():
    bundle = MockSourceBundle()
    with pytest.raises(ValueError, match="must be timezone-aware"):
        bundle.commit_source.collect_commits(
            "o", "r", datetime(2026, 11, 25), UNTIL,
        )


def test_empty_window_returns_empty_list():
    bundle = MockSourceBundle()
    assert bundle.task_source.collect_tasks(UNTIL, UNTIL) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_collectors_base.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'daily_report.collectors'`

- [ ] **Step 3: 实现**

`base.py` 三个 `Protocol` 签名严格按 `design.md` §3.1，`since` 含、`until` 不含（用 `since <= t < until` 过滤）。`MockSourceBundle` 为数据类，三个 `_Mock*Source` 内部类共用 `_in_window(record_time, since, until)` 助手，该助手先调 `ensure_utc` 校验两个边界。默认演示数据为空列表。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_collectors_base.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add src/daily_report/collectors/ tests/test_collectors_base.py
git commit -m "feat: [T3-06] 采集端口定义与离线 Mock 数据源"
```

---

## Task 7: GitHub 采集实现

**Files:**
- Create: `src/daily_report/collectors/github.py`
- Test: `tests/test_github_collector.py`

**Interfaces:**
- Consumes: `models.CommitRecord`, `net.get_json`, `errors.*`
- Produces:
  - `collectors.github.GitHubCommitSource(client: httpx.Client, token: str, max_pages: int = 10)`
    - `collect_commits(owner, repo, since, until, *, max_pages=None) -> list[CommitRecord]`
    - 内部方法 `_iter_pages(owner, repo, since, until, max_pages) -> Iterator[list[dict]]`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_github_collector.py
from datetime import datetime, timezone

import httpx
import pytest

from daily_report.collectors.github import GitHubCommitSource
from daily_report.errors import AuthenticationError, TransientError

UTC = timezone.utc
SINCE = datetime(2026, 11, 25, tzinfo=UTC)
UNTIL = datetime(2026, 11, 26, tzinfo=UTC)


def _commit(sha, when, login="zhangsan"):
    return {
        "sha": sha,
        "commit": {"message": f"work {sha}", "author": {"date": when}},
        "author": {"login": login},
    }


def _source(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GitHubCommitSource(client, token="tok")


def test_collects_and_maps_fields():
    def handler(request):
        assert request.headers["Authorization"] == "Bearer tok"
        return httpx.Response(200, json=[_commit("s1", "2026-11-25T10:00:00Z")])

    result = _source(handler).collect_commits("o", "r", SINCE, UNTIL)
    assert len(result) == 1
    record = result[0]
    assert record.sha == "s1"
    assert record.author_login == "zhangsan"
    assert record.repo == "o/r"
    assert record.committed_at == datetime(2026, 11, 25, 10, tzinfo=UTC)
    assert record.committed_at.tzinfo is not None


def test_empty_window_returns_empty_list():
    def handler(request):
        return httpx.Response(200, json=[])

    assert _source(handler).collect_commits("o", "r", SINCE, SINCE) == []


def test_401_raises_authentication_error():
    def handler(request):
        return httpx.Response(401)

    with pytest.raises(AuthenticationError):
        _source(handler).collect_commits("o", "r", SINCE, UNTIL)


def test_pagination_stops_at_max_pages(caplog):
    def handler(request):
        return httpx.Response(200, json=[_commit("s", "2026-11-25T10:00:00Z")])

    with caplog.at_level("WARNING"):
        result = _source(handler).collect_commits("o", "r", SINCE, UNTIL, max_pages=2)
    assert len(result) == 2
    assert "truncated" in caplog.text.lower()


def test_naive_since_rejected():
    def handler(request):
        return httpx.Response(200, json=[])

    with pytest.raises(ValueError, match="must be timezone-aware"):
        _source(handler).collect_commits("o", "r", datetime(2026, 11, 25), UNTIL)


def test_transient_error_propagates_after_retries():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    with pytest.raises(TransientError):
        _source(handler).collect_commits("o", "r", SINCE, UNTIL)
    assert len(calls) == 3
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_github_collector.py -v`
Expected: FAIL —— `ImportError: cannot import name 'GitHubCommitSource'`

- [ ] **Step 3: 实现**

请求 `GET {base}/{owner}/{repo}/commits`，参数 `since`/`until` 用 ISO8601 UTC（`isoformat().replace("+00:00", "Z")`）、`per_page=100`、`page=n`。`Authorization: Bearer {token}`、`Accept: application/vnd.github+json`。每页通过 `net.get_json` 取；空页则停止；达到 `max_pages` 且仍有数据时 `logging.warning("commit collection truncated at %d pages", max_pages)`。`author_login` 取 `item.get("author", {}).get("login")`，为 `None` 时用 `item["commit"]["author"]` 的 name 并加 `"(unmapped)"` 后缀，保证字段非空。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_github_collector.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add src/daily_report/collectors/github.py tests/test_github_collector.py
git commit -m "feat: [T3-08] GitHub 提交采集（UTC 区间、分页截断告警）"
```

---

## Task 8: 飞书任务与消息采集

**Files:**
- Create: `src/daily_report/collectors/feishu.py`
- Test: `tests/test_feishu_collector.py`

**Interfaces:**
- Consumes: `models.TaskRecord`, `models.MessageRecord`, `net.get_json`
- Produces:
  - `collectors.feishu.FeishuTaskSource(client, app_id, app_secret)`：`collect_tasks(since, until) -> list[TaskRecord]`
  - `collectors.feishu.FeishuMessageSource(client, app_id, app_secret)`：`collect_messages(since, until) -> list[MessageRecord]`
  - 两者共用内部 `_tenant_token(client)` 获取并缓存 tenant access token

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_feishu_collector.py
from datetime import datetime, timezone

import httpx
import pytest

from daily_report.collectors.feishu import FeishuMessageSource, FeishuTaskSource

UTC = timezone.utc
SINCE = datetime(2026, 11, 25, tzinfo=UTC)
UNTIL = datetime(2026, 11, 26, tzinfo=UTC)


def _handler(routes):
    def handler(request):
        for prefix, response in routes.items():
            if prefix in str(request.url):
                return response
        return httpx.Response(404)

    return handler


def _token_response():
    return httpx.Response(200, json={
        "code": 0, "tenant_access_token": "t-123", "expire": 7200,
    })


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_collect_tasks_maps_fields():
    body = {"code": 0, "data": {"items": [{
        "id": "task-1", "summary": "写接口",
        "completed_at": "0", "updated_at": "1764072000000",
        "members": [{"id": "ou_1", "role": "assignee"}],
    }], "has_more": False}}

    source = FeishuTaskSource(
        _client(_handler({
            "open-apis/auth/v3/tenant_access_token/internal": _token_response(),
            "open-apis/task/v2/tasks": httpx.Response(200, json=body),
        })),
        app_id="cli_x", app_secret="s",
    )
    result = source.collect_tasks(SINCE, UNTIL)
    assert len(result) == 1
    assert result[0].task_id == "task-1"
    assert result[0].title == "写接口"
    assert result[0].assignee_open_id == "ou_1"
    assert result[0].updated_at.tzinfo is not None


def test_collect_messages_marks_recalled():
    body = {"code": 0, "data": {"items": [{
        "message_id": "om_1", "msg_type": "text",
        "body": {"content": '{"text":"已撤回的消息"}'},
        "sender": {"id": "ou_1"},
        "create_time": "1764072000000",
        "deleted": True,
    }], "has_more": False}}

    source = FeishuMessageSource(
        _client(_handler({
            "open-apis/auth/v3/tenant_access_token/internal": _token_response(),
            "open-apis/im/v1/messages": httpx.Response(200, json=body),
        })),
        app_id="cli_x", app_secret="s",
    )
    result = source.collect_messages(SINCE, UNTIL)
    assert len(result) == 1
    assert result[0].is_recalled is True
    assert result[0].content == "已撤回的消息"


def test_empty_window_returns_empty_list():
    body = {"code": 0, "data": {"items": [], "has_more": False}}
    source = FeishuTaskSource(
        _client(_handler({
            "tenant_access_token": _token_response(),
            "open-apis/task/v2/tasks": httpx.Response(200, json=body),
        })),
        app_id="cli_x", app_secret="s",
    )
    assert source.collect_tasks(UNTIL, UNTIL) == []


def test_naive_window_rejected():
    source = FeishuTaskSource(_client(lambda r: httpx.Response(200)), "a", "b")
    with pytest.raises(ValueError, match="must be timezone-aware"):
        source.collect_tasks(datetime(2026, 11, 25), UNTIL)


def test_access_token_fetched_once_per_instance():
    token_calls = []

    def handler(request):
        if "tenant_access_token" in str(request.url):
            token_calls.append(request)
            return _token_response()
        return httpx.Response(200, json={"code": 0, "data": {"items": [], "has_more": False}})

    source = FeishuTaskSource(_client(handler), app_id="cli_x", app_secret="s")
    source.collect_tasks(SINCE, UNTIL)
    source.collect_tasks(SINCE, UNTIL)
    assert len(token_calls) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_feishu_collector.py -v`
Expected: FAIL —— `ImportError: cannot import name 'FeishuTaskSource'`

- [ ] **Step 3: 实现**

`_tenant_token` 用 `httpx.Client.post` 调 `/open-apis/auth/v3/tenant_access_token/internal`，body `{"app_id":..., "app_secret":...}`，缓存到实例属性 `_token`。`collect_tasks` 调 `/open-apis/task/v2/tasks`，按 `has_more` + `page_token` 翻页，字段映射：`id→task_id`、`summary→title`、`completed_at=="0"` 时 `status="open"` 否则 `"done"`、`members` 中 `role=="assignee"` 的 `id→assignee_open_id`、`updated_at`（毫秒时间戳字符串）→ UTC datetime。`collect_messages` 调 `/open-apis/im/v1/messages`，`body.content` 是 JSON 字符串，解析取 `text`；`deleted` 为真时 `is_recalled=True` 并保留记录。两个方法入口都先调 `ensure_utc(since)` / `ensure_utc(until)`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_feishu_collector.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add src/daily_report/collectors/feishu.py tests/test_feishu_collector.py
git commit -m "feat: [T3-09] 飞书任务与群消息采集（含撤回标注）"
```

---

## Task 9: 协作归属

**Files:**
- Create: `src/daily_report/generation/__init__.py`, `generation/attribution.py`
- Test: `tests/test_attribution.py`

**Interfaces:**
- Consumes: `models.Member`、`models.CommitRecord`、`models.TaskRecord`、`models.MessageRecord`
- Produces:
  - `generation.attribution.AttributionResult`（`@dataclass`：`by_member: dict[str, MemberData]`、`unmapped: list[Member]`）
  - `generation.attribution.MemberData`（`@dataclass`：`commits: list[CommitRecord]`、`tasks: list[TaskRecord]`、`messages: list[MessageRecord]`）
  - `generation.attribution.attribute(members, commits, tasks, messages) -> AttributionResult`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_attribution.py
from datetime import datetime, timezone

from daily_report.generation.attribution import attribute
from daily_report.models import CommitRecord, Member, MessageRecord, TaskRecord

UTC = timezone.utc
T = datetime(2026, 11, 25, 10, tzinfo=UTC)


def _commit(login, sha="s"):
    return CommitRecord(sha=sha, author_login=login, message="m", committed_at=T, repo="o/r")


def test_groups_commits_by_github_login():
    members = [
        Member(member_id="m1", name="张三", github_login="zhangsan"),
        Member(member_id="m2", name="李四", github_login="lisi"),
    ]
    result = attribute(members, [_commit("zhangsan"), _commit("lisi", "s2")], [], [])
    assert [c.sha for c in result.by_member["m1"].commits] == ["s"]
    assert [c.sha for c in result.by_member["m2"].commits] == ["s2"]


def test_unmapped_member_reported_not_guessed():
    members = [Member(member_id="m2", name="李四")]
    result = attribute(members, [_commit("lisi")], [], [])
    assert result.by_member["m2"].commits == []
    assert [m.member_id for m in result.unmapped] == ["m2"]


def test_unknown_author_not_attributed_to_anyone():
    members = [Member(member_id="m1", name="张三", github_login="zhangsan")]
    result = attribute(members, [_commit("stranger")], [], [])
    assert result.by_member["m1"].commits == []
    assert all(not d.commits for d in result.by_member.values())


def test_messages_not_used_to_infer_collaboration():
    members = [Member(member_id="m1", name="张三", feishu_open_id="ou_1")]
    msg = MessageRecord(
        msg_id="om1", sender_open_id="ou_1", content="我帮张三改了接口",
        created_at=T, chat_id="c1",
    )
    result = attribute(members, [], [], [msg])
    assert result.by_member["m1"].messages == [msg]
    assert result.by_member["m1"].commits == []


def test_tasks_grouped_by_assignee_open_id():
    members = [Member(member_id="m1", name="张三", feishu_open_id="ou_1")]
    task = TaskRecord(
        task_id="t1", title="写接口", status="done",
        assignee_open_id="ou_1", updated_at=T,
    )
    result = attribute(members, [], [task], [])
    assert [t.task_id for t in result.by_member["m1"].tasks] == ["t1"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_attribution.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'daily_report.generation'`

- [ ] **Step 3: 实现**

纯函数，无 IO。先建 `{github_login: member_id}` 与 `{feishu_open_id: member_id}` 两张索引；遍历记录按索引归组，索引查不到的直接丢弃（不猜测）。`by_member` 预填全部成员为空的 `MemberData`，保证"无数据成员"仍出现在结果里。`unmapped` 收集 `github_login` 与 `feishu_open_id` 均为空的成员。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_attribution.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add src/daily_report/generation/ tests/test_attribution.py
git commit -m "feat: [T3-10] 按账号映射归组，映射缺失不猜测归属"
```

---

## Task 10: 个人日报生成

**Files:**
- Create: `src/daily_report/generation/builder.py`
- Test: `tests/test_builder_personal.py`

**Interfaces:**
- Consumes: `attribution.AttributionResult`、`attribution.MemberData`、`models.*`
- Produces:
  - `generation.builder.generate_report(scope, entity_id, report_date, *, members, commits, tasks, messages, missing_sources=(), now=None) -> DailyReport`
  - 内部 `_build_personal(member, data, report_date, missing_sources, now) -> DailyReport`
  - 内部 `_to_items(data) -> list[ReportItem]`：顺序为提交 → 任务 → 消息，每条带 `source_type` / `source_id`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_builder_personal.py
from datetime import date, datetime, timezone

import pytest

from daily_report.errors import TraceabilityError
from daily_report.generation.builder import generate_report
from daily_report.models import (
    CommitRecord, Member, MessageRecord, ReportScope, TaskRecord,
)

UTC = timezone.utc
T = datetime(2026, 11, 25, 10, tzinfo=UTC)
DAY = date(2026, 11, 25)


def _member():
    return Member(member_id="m1", name="张三", github_login="zhangsan", feishu_open_id="ou_1")


def _commits():
    return [CommitRecord(sha="s1", author_login="zhangsan", message="改接口", committed_at=T, repo="o/r")]


def _tasks():
    return [TaskRecord(task_id="t1", title="写文档", status="done", assignee_open_id="ou_1", updated_at=T)]


def _messages():
    return [MessageRecord(msg_id="om1", sender_open_id="ou_1", content="同步进度", created_at=T, chat_id="c1")]


def _generate(**kwargs):
    params = dict(
        scope=ReportScope.PERSONAL, entity_id="m1", report_date=DAY,
        members=[_member()], commits=[], tasks=[], messages=[],
    )
    params.update(kwargs)
    return generate_report(**params)


def test_items_ordered_commits_tasks_messages():
    report = _generate(commits=_commits(), tasks=_tasks(), messages=_messages())
    assert [i.source_type for i in report.items] == ["github", "feishu_task", "feishu_message"]


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
    other = CommitRecord(sha="s9", author_login="lisi", message="别人的", committed_at=T, repo="o/r")
    report = _generate(commits=_commits() + [other])
    assert [i.source_id for i in report.items] == ["s1"]


def test_scope_is_required():
    with pytest.raises(TypeError):
        generate_report(entity_id="m1", report_date=DAY, members=[], commits=[], tasks=[], messages=[])


def test_empty_source_id_raises_traceability_error():
    bad = MessageRecord(msg_id="", sender_open_id="ou_1", content="x", created_at=T, chat_id="c1")
    with pytest.raises(TraceabilityError):
        _generate(messages=[bad])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_builder_personal.py -v`
Expected: FAIL —— `ImportError: cannot import name 'generate_report'`

- [ ] **Step 3: 实现**

`generate_report` 先按 `scope` 分派；本任务只实现 `PERSONAL` 分支，`TEAM` 分支 `raise NotImplementedError`（下个任务替换）。个人分支：按 `entity_id` 找到成员，调 `attribute()` 取该成员数据，`_to_items` 生成条目，`note` 组装规则——有缺失源则拼接 `来源缺失：<逗号分隔>`，无条目则 `无数据`，两者皆有则用 `；` 连接。`_to_items` 中若 `source_id` 为空抛 `TraceabilityError`。`now` 缺省用 `datetime.now(timezone.utc)`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_builder_personal.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add src/daily_report/generation/builder.py tests/test_builder_personal.py
git commit -m "feat: [T3-11] 个人日报生成与可追溯条目"
```

---

## Task 11: 团队日报生成

**Files:**
- Modify: `src/daily_report/generation/builder.py`（`TEAM` 分支）
- Test: `tests/test_builder_team.py`

**Interfaces:**
- Consumes: Task 9 的 `generate_report` 与 `_to_items`
- Produces:
  - `TEAM` 分支行为：`entity_id` 为 team_id，含全组成员条目
  - 条目 `text` 前缀为成员姓名（`"张三：改接口"`），使渲染层可按成员分组
  - `note` 记录缺失成员与无数据成员

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_builder_team.py
from datetime import date, datetime, timezone

from daily_report.generation.builder import generate_report
from daily_report.models import CommitRecord, Member, ReportScope

UTC = timezone.utc
T = datetime(2026, 11, 25, 10, tzinfo=UTC)
DAY = date(2026, 11, 25)


def _members():
    return [
        Member(member_id="m1", name="张三", github_login="zhangsan"),
        Member(member_id="m2", name="李四", github_login="lisi"),
    ]


def _team(commits, members=None, **kwargs):
    return generate_report(
        scope=ReportScope.TEAM, entity_id="team-1", report_date=DAY,
        members=members or _members(), commits=commits, tasks=[], messages=[], **kwargs,
    )


def test_items_grouped_by_member_not_by_commit_count():
    commits = [
        CommitRecord(sha=f"z{i}", author_login="zhangsan", message="m", committed_at=T, repo="o/r")
        for i in range(3)
    ] + [CommitRecord(sha="l1", author_login="lisi", message="m", committed_at=T, repo="o/r")]
    report = _team(commits)
    texts = [i.text for i in report.items]
    assert sum(t.startswith("张三：") for t in texts) == 3
    assert sum(t.startswith("李四：") for t in texts) == 1


def test_member_without_data_still_listed_in_note():
    commits = [CommitRecord(sha="z1", author_login="zhangsan", message="m", committed_at=T, repo="o/r")]
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_builder_team.py -v`
Expected: FAIL —— `test_items_grouped_by_member_not_by_commit_count` 断言失败（`TEAM` 分支仍是 `NotImplementedError`）

- [ ] **Step 3: 实现**

`TEAM` 分支：调 `attribute()` 得到 `by_member`，按 `members` 的声明顺序遍历（保证输出稳定），对每个成员用 `_to_items` 生成条目并加 `f"{member.name}："` 前缀，拼接成一个列表。`note` 由三部分组成：`unmapped` 里的姓名 → `未配置映射成员：A、B`；`by_member` 中数据全空的成员 → `无数据成员：C、D`；`missing_sources` → `来源缺失：x`。三者用 `；` 连接，皆空则 `note=None`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_builder_team.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add src/daily_report/generation/builder.py tests/test_builder_team.py
git commit -m "feat: [T3-12] 团队日报按成员归组，缺失成员显式标注"
```

---

## Task 12: 渲染层

**Files:**
- Create: `src/daily_report/render/__init__.py`, `render/text.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `models.DailyReport`, `models.ReportItem`
- Produces:
  - `render.text.render_text(report: DailyReport) -> str`
  - `render.text.render_email_html(report: DailyReport) -> str`
  - `render.text.render_team_text(report: DailyReport) -> str`
  - 三者均为纯函数，不修改入参

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_render.py
import copy
from datetime import date, datetime, timezone

from daily_report.models import DailyReport, ReportItem, ReportScope
from daily_report.render.text import render_email_html, render_team_text, render_text

UTC = timezone.utc
T = datetime(2026, 11, 25, 10, tzinfo=UTC)


def _report(items, note=None, scope=ReportScope.PERSONAL):
    return DailyReport(
        scope=scope, entity_id="m1", report_date=date(2026, 11, 25),
        items=items, generated_at=T, note=note,
    )


def _items():
    return [
        ReportItem(source_type="github", source_id="s1", text="改接口", occurred_at=T),
        ReportItem(source_type="feishu_message", source_id="om1", text="<b>同步</b>", occurred_at=T),
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_render.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'daily_report.render'`

- [ ] **Step 3: 实现**

`render_text` 输出形如：标题行 `2026-11-25 个人日报`（团队则 `团队日报`）、每条形如 `- [github] 改接口`、`note` 存在时末尾追加 `备注：<note>`。`render_email_html` 用标准库 `html.escape` 转义每个 `item.text`，包一层简单 `<ul><li>`，同样转义 `note`。`render_team_text` 按 `text` 中第一个 `：` 切分得到成员名，据此分组输出，切不出成员名的归入"其他"。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_render.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add src/daily_report/render/ tests/test_render.py
git commit -m "feat: [T3-13] 文本与 HTML 渲染（纯函数、HTML 转义）"
```

---

## Task 13: 邮件推送

**Files:**
- Create: `src/daily_report/publishers/__init__.py`, `publishers/base.py`, `publishers/email.py`
- Test: `tests/test_email_pusher.py`

**Interfaces:**
- Consumes: `models.DailyReport`, `render.text.render_email_html`, `config.Settings`
- Produces:
  - `publishers.base.SendResult(success: list[str], failed: list[tuple[str, str]])`
  - `publishers.base.PushResult(ok: bool, error: str | None = None)`
  - `publishers.base.EmailPublisher`、`BotPublisher`（`Protocol`）
  - `publishers.email.SmtpEmailPublisher(settings, send_fn=None)`：`send_email(report, recipients) -> SendResult` —— `send_fn` 可注入以便测试
  - `publishers.email.mask_email(address: str) -> str`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_email_pusher.py
import smtplib
from datetime import date, datetime, timezone

import pytest

from daily_report.config import load_settings
from daily_report.models import DailyReport, ReportScope
from daily_report.publishers.email import SmtpEmailPublisher, mask_email

UTC = timezone.utc
T = datetime(2026, 11, 25, 10, tzinfo=UTC)


def _report():
    return DailyReport(
        scope=ReportScope.PERSONAL, entity_id="m1", report_date=date(2026, 11, 25),
        items=[], generated_at=T,
    )


def _settings():
    return load_settings({
        "SMTP_HOST": "smtp.test", "SMTP_PORT": "465",
        "SMTP_USER": "bot@test", "SMTP_PASSWORD": "pw",
    })


def test_mask_email():
    assert mask_email("zhangsan@example.com") == "z***@example.com"


def test_partial_failure_does_not_stop_batch():
    sent = []

    def send_fn(msg, recipients):
        if recipients == "bad@test":
            raise smtplib.SMTPException("boom")
        sent.append(recipients)

    publisher = SmtpEmailPublisher(_settings(), send_fn=send_fn)
    result = publisher.send_email(_report(), ["a@test", "bad@test", "c@test"])
    assert result.success == ["a@test", "c@test"]
    assert [r for r, _ in result.failed] == ["bad@test"]
    assert sent == ["a@test", "c@test"]


def test_auth_failure_stops_whole_batch():
    calls = []

    def send_fn(msg, recipients):
        calls.append(recipients)
        raise smtplib.SMTPAuthenticationError(535, b"auth")

    publisher = SmtpEmailPublisher(_settings(), send_fn=send_fn)
    result = publisher.send_email(_report(), ["a@test", "b@test"])
    assert len(calls) == 1
    assert len(result.failed) == 2


def test_failure_reason_does_not_leak_full_address():
    def send_fn(msg, recipients):
        raise smtplib.SMTPException("failed for secret@test")

    publisher = SmtpEmailPublisher(_settings(), send_fn=send_fn)
    result = publisher.send_email(_report(), ["bad@test"])
    reason = result.failed[0][1]
    assert "bad@test" not in reason


def test_missing_smtp_config_raises_config_error():
    from daily_report.errors import ConfigError
    publisher = SmtpEmailPublisher(load_settings({}))
    with pytest.raises(ConfigError):
        publisher.send_email(_report(), ["a@test"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_email_pusher.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'daily_report.publishers'`

- [ ] **Step 3: 实现**

`mask_email` 保留本地部分首字符与完整域名。`SmtpEmailPublisher` 构造时保存 settings；未注入 `send_fn` 时构造真实 `smtplib.SMTP_SSL(host, port)` 并 `login`。`send_email` 先校验 `smtp_host` 等必需项，缺失抛 `ConfigError`。逐收件人 `try` 发送，`SMTPAuthenticationError` 视为整批失败（把剩余收件人一并记入 `failed`）并 `break`；其它异常记入 `failed` 后继续。失败原因统一经 `mask_email` 与文本清洗，确保不含完整地址。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_email_pusher.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add src/daily_report/publishers/ tests/test_email_pusher.py
git commit -m "feat: [T3-14] 邮件推送：部分失败隔离、邮箱脱敏"
```

---

## Task 14: 飞书机器人推送与 Fake 推送器

**Files:**
- Create: `src/daily_report/publishers/feishu_bot.py`, `publishers/fake.py`
- Test: `tests/test_feishu_bot.py`

**Interfaces:**
- Consumes: `publishers.base.PushResult`、`net.get_json` 的同类重试逻辑（改用 `post_json`）
- Produces:
  - `net.post_json(client, url, *, json_body, retry_times=2, sleep=time.sleep) -> dict`（在 `net.py` 中补充）
  - `publishers.feishu_bot.WebhookBotPublisher(client, webhook=None, retry_times=2)`：`push_to_feishu(report, webhook=None) -> PushResult`
  - `publishers.fake.FakePublisher`：实现 `EmailPublisher` 与 `BotPublisher`，记录调用并可控失败

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_feishu_bot.py
from datetime import date, datetime, timezone

import httpx
import pytest

from daily_report.errors import ConfigError
from daily_report.models import DailyReport, ReportScope
from daily_report.publishers.feishu_bot import WebhookBotPublisher

UTC = timezone.utc


def _report():
    return DailyReport(
        scope=ReportScope.TEAM, entity_id="t1", report_date=date(2026, 11, 25),
        items=[], generated_at=datetime(2026, 11, 25, tzinfo=UTC),
    )


def _publisher(handler, webhook="https://hook.test/x"):
    return WebhookBotPublisher(
        httpx.Client(transport=httpx.MockTransport(handler)), webhook=webhook,
    )


def test_success_returns_ok():
    publisher = _publisher(lambda r: httpx.Response(200, json={"code": 0}))
    assert publisher.push_to_feishu(_report()).ok is True


def test_5xx_retried_then_reports_failure():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    result = _publisher(handler).push_to_feishu(_report())
    assert result.ok is False
    assert len(calls) == 3


def test_missing_webhook_raises_config_error():
    publisher = _publisher(lambda r: httpx.Response(200), webhook=None)
    with pytest.raises(ConfigError):
        publisher.push_to_feishu(_report())


def test_feishu_business_error_reports_failure():
    publisher = _publisher(lambda r: httpx.Response(200, json={"code": 19001, "msg": "bad"}))
    result = publisher.push_to_feishu(_report())
    assert result.ok is False
    assert "19001" in result.error
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_feishu_bot.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'daily_report.publishers.feishu_bot'`

- [ ] **Step 3: 实现**

`net.post_json` 与 `get_json` 共用 `_classify` 与退避逻辑（提取公共 `_request_with_retry`）。`WebhookBotPublisher.push_to_feishu` 组装 `{"msg_type":"text","content":{"text": render_text(report)}}`，调 `post_json`；HTTP 层异常由 `net` 抛 `TransientError`，此处捕获并转成 `PushResult(ok=False, error=str(exc))`；响应 JSON 中 `code != 0` 同样转失败。`FakePublisher` 记录 `calls` 列表，支持 `fail_email=True` / `fail_bot=True` 开关，用于编排层测试。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_feishu_bot.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add src/daily_report/net.py src/daily_report/publishers/ tests/test_feishu_bot.py
git commit -m "feat: [T3-15] 飞书机器人推送与测试用 Fake 推送器"
```

---

## Task 15: 主编排与幂等

**Files:**
- Create: `src/daily_report/orchestration/__init__.py`, `orchestration/run_daily.py`
- Test: `tests/test_run_daily.py`

**Interfaces:**
- Consumes: `Repository`、`SourceBundle`、`PublisherBundle`、`generate_report`、`Settings`
- Produces:
  - `orchestration.run_daily.PublisherBundle`（`@dataclass`：`email: EmailPublisher`、`bot: BotPublisher | None = None`）
  - `orchestration.run_daily.run_daily(team_id, report_date, *, settings, repo, sources, publishers, now=None) -> RunSummary`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_run_daily.py
from datetime import date, datetime, timezone

import pytest

from daily_report.collectors.base import SourceBundle
from daily_report.collectors.mock import MockSourceBundle
from daily_report.config import load_settings
from daily_report.generation.builder import generate_report  # noqa: F401  (接口存在性)
from daily_report.models import (
    CommitRecord, Member, ReportScope, RunSummary,
)
from daily_report.orchestration.run_daily import PublisherBundle, run_daily
from daily_report.publishers.fake import FakePublisher
from daily_report.storage.repository import Repository
from daily_report.storage.schema import init_db

UTC = timezone.utc
T = datetime(2026, 11, 25, 10, tzinfo=UTC)
DAY = date(2026, 11, 25)


class FailingSource:
    def collect_commits(self, owner, repo, since, until, *, max_pages=10):
        raise RuntimeError("github down")


@pytest.fixture
def repo(tmp_path):
    conn = init_db(str(tmp_path / "r.db"))
    repository = Repository(conn)
    repository.upsert_members([
        Member(member_id="m1", name="张三", github_login="zhangsan", email="a@test"),
    ])
    return repository


def _run(repo, sources=None, publishers=None):
    return run_daily(
        "team-1", DAY,
        settings=load_settings({}),
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
    summary = _run(repo)
    assert summary.status == "skipped"
    assert len(repo.list_reports(DAY, DAY)) == 1


def test_single_source_failure_does_not_abort(repo):
    publishers = PublisherBundle(email=FakePublisher())
    summary = run_daily(
        "team-1", DAY, settings=load_settings({}), repo=repo,
        sources=SourceBundle(FailingSource(), MockSourceBundle().task_source, MockSourceBundle().message_source),
        publishers=publishers, now=T,
    )
    assert summary.status in ("success", "partial")
    assert "github" in str(summary.failed)


def test_push_failure_keeps_report(repo):
    publishers = PublisherBundle(email=FakePublisher(fail_email=True))
    summary = _run(repo, publishers=publishers)
    assert summary.status in ("success", "partial")
    assert repo.get_report(ReportScope.TEAM, "team-1", DAY) is not None


def test_report_persisted_for_all_members(repo):
    _run(repo)
    assert repo.get_report(ReportScope.PERSONAL, "m1", DAY) is not None
    assert repo.get_report(ReportScope.TEAM, "team-1", DAY) is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_run_daily.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'daily_report.orchestration'`

- [ ] **Step 3: 实现**

`run_daily` 流程：① `repo.find_successful_run` 命中则返回 `RunSummary(status="skipped")`；② 计算 `since`/`until`（`report_date` 在 `settings.timezone` 的 00:00 到次日 00:00，转 UTC）；③ 逐源调用采集，`except ReportError` 与 `except Exception` 都记录到 `failed[source_name]` 并继续；④ 落库原始记录；⑤ 对每个成员生成 `PERSONAL` 日报并入库，再生成 `TEAM` 日报入库；⑥ 推送（`publishers.email` 与可选 `bot`），`SendResult.failed` 并入 `RunSummary.failed`；⑦ 写 `RunSummary`，状态判定：有任何失败 → `partial`，全部成功 → `success`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_run_daily.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add src/daily_report/orchestration/ tests/test_run_daily.py
git commit -m "feat: [T3-16] 主编排：幂等、失败隔离、摘要落库"
```

---

## Task 16: 命令行入口

**Files:**
- Create: `src/daily_report/cli.py`, `src/daily_report/__main__.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_daily`、`load_settings`、`init_db`、`Repository`、`MockSourceBundle`/真实采集器装配、`PublisherBundle`
- Produces:
  - `cli.main(argv: list[str] | None = None) -> int`
  - 子命令 `run --team TEAM_ID [--date YYYY-MM-DD] [--db PATH]`
  - 退出码：成功 0；重复触发 0（并打印"重复触发已忽略"）；参数错误 2

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_cli.py
from daily_report.cli import main


def test_run_returns_zero(tmp_path, capsys):
    code = main(["run", "--team", "t1", "--date", "2026-11-25", "--db", str(tmp_path / "c.db")])
    assert code == 0
    assert "success" in capsys.readouterr().out


def test_repeat_run_reports_skipped(tmp_path, capsys):
    args = ["run", "--team", "t1", "--date", "2026-11-25", "--db", str(tmp_path / "c.db")]
    main(args)
    assert main(args) == 0
    assert "重复触发已忽略" in capsys.readouterr().out


def test_invalid_date_returns_2(tmp_path):
    code = main(["run", "--team", "t1", "--date", "not-a-date", "--db", str(tmp_path / "c.db")])
    assert code == 2


def test_missing_team_returns_2(tmp_path):
    assert main(["run", "--db", str(tmp_path / "c.db")]) == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'daily_report.cli'`

- [ ] **Step 3: 实现**

用 `argparse`，`--date` 通过 `date.fromisoformat` 校验，失败时让 argparse 返回 2（`parser.error` 会抛 `SystemExit(2)`，在 `main` 中捕获并返回 2）。按 `settings.source_mode` 装配 Mock 或真实采集器（真实采集器在此处组装 `httpx.Client` 与各自的 token）。打印 `summary.status` 与摘要 JSON；`skipped` 时额外打印"重复触发已忽略"。`__main__.py` 为 `sys.exit(cli.main())`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add src/daily_report/cli.py src/daily_report/__main__.py tests/test_cli.py
git commit -m "feat: [T3-17] 命令行入口与退出码"
```

---

## Task 17: 集成测试与分层检查

**Files:**
- Create: `tests/test_integration.py`, `tests/test_architecture.py`
- Test: 同左

**Interfaces:**
- Consumes: 全部模块
- Produces: 无新增公共接口

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_integration.py
import json
from datetime import date, datetime, timezone

from daily_report.collectors.mock import MockSourceBundle
from daily_report.config import load_settings
from daily_report.models import CommitRecord, Member, MessageRecord, ReportScope, TaskRecord
from daily_report.orchestration.run_daily import PublisherBundle, run_daily
from daily_report.publishers.fake import FakePublisher
from daily_report.storage.repository import Repository
from daily_report.storage.schema import init_db

UTC = timezone.utc
T = datetime(2026, 11, 25, 10, tzinfo=UTC)
DAY = date(2026, 11, 25)


def test_full_pipeline_end_to_end(tmp_path):
    repo = Repository(init_db(str(tmp_path / "e2e.db")))
    repo.upsert_members([Member(
        member_id="m1", name="张三", github_login="zhangsan",
        feishu_open_id="ou_1", email="a@test",
    )])
    sources = MockSourceBundle(
        commits=[CommitRecord(sha="s1", author_login="zhangsan", message="改接口",
                              committed_at=T, repo="o/r")],
        tasks=[TaskRecord(task_id="t1", title="写文档", status="done",
                          assignee_open_id="ou_1", updated_at=T)],
        messages=[MessageRecord(msg_id="om1", sender_open_id="ou_1", content="同步",
                                created_at=T, chat_id="c1")],
    )
    publisher = FakePublisher()
    summary = run_daily(
        "team-1", DAY, settings=load_settings({}), repo=repo,
        sources=sources, publishers=PublisherBundle(email=publisher), now=T,
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
    repo.upsert_members([Member(member_id="m1", name="张三", github_login="zhangsan")])
    sources = MockSourceBundle(commits=[CommitRecord(
        sha="s1", author_login="zhangsan", message="m", committed_at=T, repo="o/r",
    )])
    args = dict(settings=load_settings({}), repo=repo, sources=sources,
                publishers=PublisherBundle(email=FakePublisher()), now=T)
    run_daily("team-1", DAY, **args)
    before = len(repo.list_reports(DAY, DAY))
    run_daily("team-1", DAY, **args)
    assert len(repo.list_reports(DAY, DAY)) == before
```

```python
# tests/test_architecture.py
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "daily_report"
LAYERED = ("collectors", "generation", "publishers", "render", "storage")
FORBIDDEN = "orchestration"


def test_lower_layers_do_not_import_orchestration():
    offenders = []
    for package in LAYERED:
        for path in (SRC / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and FORBIDDEN in node.module:
                    offenders.append(str(path))
                if isinstance(node, ast.Import):
                    offenders += [str(path) for a in node.names if FORBIDDEN in a.name]
    assert offenders == []


def test_sql_only_in_repository_module():
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.name in {"repository.py", "schema.py"}:
            continue
        text = path.read_text(encoding="utf-8").upper()
        if "INSERT INTO" in text or ("SELECT " in text and "FROM " in text):
            offenders.append(str(path))
    assert offenders == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_integration.py tests/test_architecture.py -v`
Expected: FAIL —— 两条集成用例可能通过，但 `test_sql_only_in_repository_module` 应失败（`mock.py` 或其它模块若含 SQL 片段）；若三条全过则说明用例无覆盖力，需检查断言

- [ ] **Step 3: 修正**

若分层检查失败，把违规的 SQL 或 import 移回正确模块；若集成测试失败，按断言调整实现。**不允许通过放宽断言让测试变绿**——断言表达的是规范要求。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_integration.py tests/test_architecture.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add tests/test_integration.py tests/test_architecture.py
git commit -m "test: [T3-17] 全链路集成测试与分层依赖检查"
```

---

## Task 18: 质量收口与规范一致性记录

**Files:**
- Modify: `docs/设计与specs一致性检查记录.md`（重写为真实内容）
- Modify: `specs/tasks.md`（状态列与提交号回填）
- Test: 全量

- [ ] **Step 1: 运行全量检查**

Run: `uv run ruff check . && uv run pytest -q`
Expected: ruff 无输出（零告警）；pytest 全绿。若有失败，先修复再继续。

- [ ] **Step 2: 生成覆盖率数据**

Run: `uv run pytest --cov=daily_report --cov-report=term-missing -q`
Expected: 输出每模块覆盖率。记录真实数字，**不得编造**。

- [ ] **Step 3: 重写一致性检查记录**

按实际代码逐行填写 `docs/设计与specs一致性检查记录.md`：接口契约对照表的"代码位置"列必须指向真实存在的文件与行号；数据模型表、任务覆盖表、ADR 约束表同样。删除所有指向不存在文件的行。

- [ ] **Step 4: 回填任务状态**

`specs/tasks.md` 的 T3-01~T3-17 状态改为 `DONE`，并在任务表新增"提交号"列填入真实 commit（用 `git log --oneline` 核对）。并发一条真实的工作流记录（红绿循环记录）到 `docs/工作流执行记录.md`。

- [ ] **Step 5: 提交**

```bash
git add docs/ specs/
git commit -m "docs: [T3-18] 一致性检查记录与任务状态回填"
```

---

## 第 4 周任务

> 以下任务在第 3 周全部通过后执行。变更单内容按指导书第 4 周任务书：**新增飞书考勤数据采集模块**。

### Task 19: 变更单受理与规范同步

**Files:**
- Modify: `specs/proposal.md`（新增 R-11）、`specs/design.md`（新增 §3.6、ADR-005）
- Create: `docs/变更涟漪演练记录.md`
- Test: 无代码测试，验证文档 diff 完整

**Interfaces:**
- Produces: `models.AttendanceRecord(record_id, member_open_id, work_date, status, checked_in_at, checked_out_at)` —— 供 Task 20 使用

- [ ] **Step 1: 在 `design.md` 追加 §3.6 接口契约**

```python
class AttendanceSource(Protocol):
    def collect_attendance(self, since: datetime, until: datetime) -> list[AttendanceRecord]: ...
```

以及 ADR-005（数据源扩展方式：新增 Protocol 而非修改既有签名），含备选项与理由。

- [ ] **Step 2: 在 `proposal.md` 追加 R-11 与 AC-10**

R-11：采集飞书考勤数据并纳入日报条目；AC-10：考勤条目具备 `source_type="feishu_attendance"` 且 `source_id` 非空。

- [ ] **Step 3: 写 `docs/变更涟漪演练记录.md`**

记录：变更单原文、影响的规范条目（proposal R-11、design §3.6/ADR-005、tasks T4-03~T4-05）、受影响的既有任务（T3-09 生成层需容纳新来源）、以及"规范先改、代码后改"的顺序证据。

- [ ] **Step 4: 提交**

```bash
git add specs/ docs/变更涟漪演练记录.md
git commit -m "docs: [T4-01] 变更单受理：考勤采集的范围、接口与数据模型同步"
```

---

### Task 20: 考勤采集实现

**Files:**
- Modify: `src/daily_report/models.py`（新增 `AttendanceRecord`）
- Modify: `src/daily_report/collectors/feishu.py`（新增 `FeishuAttendanceSource`）
- Modify: `src/daily_report/collectors/mock.py`（新增 `attendance` 数据与 `attendance_source`）
- Modify: `src/daily_report/collectors/base.py`（`SourceBundle` 增加 `attendance_source: AttendanceSource | None = None`）
- Test: `tests/test_attendance.py`

**Interfaces:**
- Produces: `collectors.feishu.FeishuAttendanceSource.collect_attendance(since, until) -> list[AttendanceRecord]`；`MockSourceBundle(attendance=[...])`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_attendance.py
from datetime import datetime, timezone

import pytest

from daily_report.collectors.mock import MockSourceBundle
from daily_report.errors import TraceabilityError
from daily_report.models import AttendanceRecord

UTC = timezone.utc
SINCE = datetime(2026, 11, 25, tzinfo=UTC)
UNTIL = datetime(2026, 11, 26, tzinfo=UTC)


def test_attendance_record_requires_source_id():
    with pytest.raises(ValueError, match="record_id"):
        AttendanceRecord(
            record_id="", member_open_id="ou_1", work_date=SINCE.date(),
            status="present", checked_in_at=SINCE, checked_out_at=SINCE,
        )


def test_mock_collects_attendance_in_window():
    record = AttendanceRecord(
        record_id="att-1", member_open_id="ou_1", work_date=SINCE.date(),
        status="present", checked_in_at=SINCE, checked_out_at=SINCE,
    )
    bundle = MockSourceBundle(attendance=[record])
    assert bundle.attendance_source.collect_attendance(SINCE, UNTIL) == [record]


def test_absence_record_supported():
    record = AttendanceRecord(
        record_id="att-2", member_open_id="ou_1", work_date=SINCE.date(),
        status="absent", checked_in_at=None, checked_out_at=None,
    )
    assert record.status == "absent"


def test_empty_window_returns_empty_list():
    assert MockSourceBundle().attendance_source.collect_attendance(UNTIL, UNTIL) == []


def test_naive_window_rejected():
    with pytest.raises(ValueError, match="must be timezone-aware"):
        MockSourceBundle().attendance_source.collect_attendance(
            datetime(2026, 11, 25), UNTIL,
        )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_attendance.py -v`
Expected: FAIL —— `ImportError: cannot import name 'AttendanceRecord'`

- [ ] **Step 3: 实现**

`AttendanceRecord` 为 `frozen dataclass`：`record_id`、`member_open_id`、`work_date: date`、`status: str`（`"present"|"absent"|"late"|"leave"`）、`checked_in_at: datetime | None`、`checked_out_at: datetime | None`；`__post_init__` 校验 `record_id` 非空、非 None 的时间为 UTC。`FeishuAttendanceSource` 调 `/open-apis/attendance/v1/user_tasks/query`，字段映射到 `AttendanceRecord`。`MockSourceBundle` 新增 `attendance` 参数与 `attendance_source` 属性，实现同一 `Protocol`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_attendance.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add src/daily_report/models.py src/daily_report/collectors/ tests/test_attendance.py
git commit -m "feat: [T4-03] 考勤数据采集（规范变更后实现）"
```

---

### Task 21: 生成层容纳考勤条目

**Files:**
- Modify: `src/daily_report/generation/attribution.py`（`MemberData` 增加 `attendance`）
- Modify: `src/daily_report/generation/builder.py`（接入考勤条目）
- Test: `tests/test_builder_attendance.py`

**Interfaces:**
- Consumes: `models.AttendanceRecord`
- Produces: 条目 `source_type="feishu_attendance"`，文本形如 `考勤：出勤 09:12`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_builder_attendance.py
from datetime import date, datetime, timezone

from daily_report.generation.builder import generate_report
from daily_report.models import AttendanceRecord, Member, ReportScope

UTC = timezone.utc
T = datetime(2026, 11, 25, 1, 12, tzinfo=UTC)
DAY = date(2026, 11, 25)


def _member():
    return Member(member_id="m1", name="张三", feishu_open_id="ou_1")


def test_attendance_item_added_with_traceable_source():
    attendance = [AttendanceRecord(
        record_id="att-1", member_open_id="ou_1", work_date=DAY,
        status="present", checked_in_at=T, checked_out_at=None,
    )]
    report = generate_report(
        scope=ReportScope.PERSONAL, entity_id="m1", report_date=DAY,
        members=[_member()], commits=[], tasks=[], messages=[],
        attendance=attendance,
    )
    assert len(report.items) == 1
    assert report.items[0].source_type == "feishu_attendance"
    assert report.items[0].source_id == "att-1"


def test_absence_marked_in_item_text():
    attendance = [AttendanceRecord(
        record_id="att-2", member_open_id="ou_1", work_date=DAY,
        status="absent", checked_in_at=None, checked_out_at=None,
    )]
    report = generate_report(
        scope=ReportScope.PERSONAL, entity_id="m1", report_date=DAY,
        members=[_member()], commits=[], tasks=[], messages=[],
        attendance=attendance,
    )
    assert "缺勤" in report.items[0].text


def test_no_attendance_keeps_backward_compatible_behavior():
    report = generate_report(
        scope=ReportScope.PERSONAL, entity_id="m1", report_date=DAY,
        members=[_member()], commits=[], tasks=[], messages=[],
    )
    assert report.items == []
    assert report.note == "无数据"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_builder_attendance.py -v`
Expected: FAIL —— `TypeError: generate_report() got an unexpected keyword argument 'attendance'`

- [ ] **Step 3: 实现**

`generate_report` 增加关键字参数 `attendance: Sequence[AttendanceRecord] = ()`（默认空，保证既有调用不变）。`attribute()` 增加同名参数，`MemberData.attendance` 按 `member_open_id` 归组。条目文本：`present` → `考勤：出勤 HH:MM`（团队时区）、`absent` → `考勤：缺勤`、`late` → `考勤：迟到 HH:MM`、`leave` → `考勤：请假`。条目插入位置由 `Settings.attendance_position`（`"after_commits" | "end"`，默认 `"end"`）决定。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_builder_attendance.py tests/test_builder_personal.py tests/test_builder_team.py -v`
Expected: 15 passed（3 + 7 + 5）—— 既有用例不回归

- [ ] **Step 5: 提交**

```bash
git add src/daily_report/generation/ tests/test_builder_attendance.py
git commit -m "feat: [T4-04] 日报生成容纳考勤条目，既有行为不回归"
```

---

### Task 22: 全量回归

**Files:**
- Create: `tests/test_regression.py`
- Create: `docs/回归测试执行报告.md`

**Interfaces:**
- Consumes: 全部模块

- [ ] **Step 1: 从成功标准导出回归用例**

```python
# tests/test_regression.py
"""从 specs/proposal.md §5 成功标准逐条导出的回归测试。"""
from datetime import date, datetime, timezone

import pytest

from daily_report.collectors.mock import MockSourceBundle
from daily_report.config import load_settings
from daily_report.models import (
    AttendanceRecord, CommitRecord, Member, ReportScope, TaskRecord,
)
from daily_report.orchestration.run_daily import PublisherBundle, run_daily
from daily_report.publishers.fake import FakePublisher
from daily_report.storage.repository import Repository
from daily_report.storage.schema import init_db

UTC = timezone.utc
T = datetime(2026, 11, 25, 10, tzinfo=UTC)
DAY = date(2026, 11, 25)


@pytest.fixture
def env(tmp_path):
    repo = Repository(init_db(str(tmp_path / "reg.db")))
    repo.upsert_members([Member(
        member_id="m1", name="张三", github_login="zhangsan",
        feishu_open_id="ou_1", email="a@test",
    )])
    sources = MockSourceBundle(
        commits=[CommitRecord(sha="s1", author_login="zhangsan", message="m",
                              committed_at=T, repo="o/r")],
        tasks=[TaskRecord(task_id="t1", title="写文档", status="done",
                          assignee_open_id="ou_1", updated_at=T)],
        messages=[],
        attendance=[AttendanceRecord(record_id="att-1", member_open_id="ou_1",
                                     work_date=DAY, status="present",
                                     checked_in_at=T, checked_out_at=None)],
    )
    return repo, sources


def _run(repo, sources, **kwargs):
    return run_daily(
        "team-1", DAY, settings=load_settings({}), repo=repo,
        sources=sources, publishers=PublisherBundle(email=FakePublisher()), now=T, **kwargs,
    )


def test_ac01_three_sources_collected(env):
    repo, sources = env
    summary = _run(repo, sources)
    assert set(summary.collected) >= {"github", "feishu_task", "feishu_message"}


def test_ac02_personal_report_fully_traceable(env):
    repo, sources = env
    _run(repo, sources)
    report = repo.get_report(ReportScope.PERSONAL, "m1", DAY)
    assert all(item.source_id for item in report.items)


def test_ac03_team_report_grouped(env):
    repo, sources = env
    _run(repo, sources)
    team = repo.get_report(ReportScope.TEAM, "team-1", DAY)
    assert all("：" in item.text for item in team.items)


def test_ac06_second_run_is_idempotent(env):
    repo, sources = env
    _run(repo, sources)
    second = _run(repo, sources)
    assert second.status == "skipped"


def test_ac10_attendance_items_traceable(env):
    repo, sources = env
    _run(repo, sources)
    report = repo.get_report(ReportScope.PERSONAL, "m1", DAY)
    attendance = [i for i in report.items if i.source_type == "feishu_attendance"]
    assert attendance and all(i.source_id == "att-1" for i in attendance)
```

- [ ] **Step 2: 跑测试确认通过**

Run: `uv run pytest -q`
Expected: 全部通过。任一失败按 systematic-debugging 处理，禁止跳过。

- [ ] **Step 3: 写回归报告**

`docs/回归测试执行报告.md` 逐条列出 AC-01~AC-10，每条标注对应测试函数名与执行结果，附 `pytest -q` 的真实输出。

- [ ] **Step 4: 提交**

```bash
git add tests/test_regression.py docs/回归测试执行报告.md
git commit -m "test: [T4-05] 从成功标准导出的全量回归"
```

---

### Task 23: 规范守护自检

**Files:**
- Create: `scripts/check_spec_drift.py`
- Create: `docs/规范守护自检记录.md`

**Interfaces:**
- Produces: 脚本退出码 0（无漂移）或 1（有漂移并列出文件）

- [ ] **Step 1: 写脚本**

逻辑：`git diff --name-only HEAD~1` 取改动文件；若存在 `src/**/*.py` 改动但无 `specs/**` 改动，则打印提示并退出 1；否则退出 0。支持 `--base REV` 参数指定比较基准。

- [ ] **Step 2: 验证两种情形**

```bash
uv run python scripts/check_spec_drift.py --base HEAD~1   # 应输出结果
```

分别制造一次"只改 src"与"src+specs 同改"的情形验证退出码，结果写入 `docs/规范守护自检记录.md`（含真实终端输出）。

- [ ] **Step 3: 提交**

```bash
git add scripts/check_spec_drift.py docs/规范守护自检记录.md
git commit -m "feat: [T4-06] 规范守护脚本：代码改动须伴随规范改动"
```

---

### Task 24: 安全自检与答辩材料

**Files:**
- Create: `docs/安全自检记录.md`, `docs/答辩追问清单.md`, `docs/模拟答辩记录.md`

- [ ] **Step 1: 执行安全检索并记录真实输出**

```bash
rg -n "ghp_|xoxb-|password\s*=\s*['\"]" src tests || echo "无匹配"
rg -n "execute\(f\"|execute\(.*\+|%" src/daily_report/storage || echo "无匹配"
```

把命令与输出原样写入 `docs/安全自检记录.md`，注明结论。

- [ ] **Step 2: 写答辩追问清单**

覆盖四类各 3 问：架构 ADR（为何 httpx/sqlite3、为何端口适配器）、安全（令牌如何注入、日志如何脱敏）、异常处理（单源失败、全推送失败、分页截断）、并发与幂等（同日重复触发、WAL 与并发写）。每问附可在代码中核对的答案位置。

- [ ] **Step 3: 组织模拟答辩并记录**

`docs/模拟答辩记录.md` 记录问答过程与暴露的问题，问题转为待办并修复。

- [ ] **Step 4: 提交**

```bash
git add docs/
git commit -m "docs: [T4-07][T4-08] 安全自检与答辩材料"
```

---

### Task 25: 总结与审计报告

**Files:**
- Create: `docs/项目总结报告.md`, `docs/规范审计报告.md`, `docs/AI使用合规声明.md`
- Modify: `specs/tasks.md`（第 4 周任务状态回填）

- [ ] **Step 1: 收集真实数据**

```bash
uv run pytest --cov=daily_report --cov-report=term-missing -q
uv run ruff check . --statistics
git log --oneline | wc -l
```

- [ ] **Step 2: 写报告**

按指导书第八部分章节结构撰写。质量数据只写实测值，缺测项标注"未测"并说明原因，**不得编造**。两阶段对比表中 v1 数据若无可核证据，标明"v1 数据待补/无法核实"，不填猜测值。

- [ ] **Step 3: 回填 tasks.md 并提交**

```bash
git add docs/ specs/
git commit -m "docs: [T4-09] 总结报告、规范审计与合规声明"
```

---

## 验证清单

全部任务完成后逐项核对：

- [ ] `uv run ruff check .` 零告警
- [ ] `uv run pytest -q` 全绿
- [ ] `python -m daily_report run --team t1 --date 2026-11-25 --db demo.db` 可运行并打印摘要
- [ ] 全仓无真实令牌（`rg "ghp_|xoxb-" .` 无匹配）
- [ ] 每条日报条目有非空 `source_id`
- [ ] 同日重复运行返回 `skipped` 且不产生第二份日报
- [ ] `specs/` 三份规范与代码逐条对应
- [ ] `docs/` 中无指向不存在文件或提交的引用