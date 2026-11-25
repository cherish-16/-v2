# design.md：智能日报生成器（v2）

| 项目 | 内容 |
|---|---|
| 关联规范 | `specs/proposal.md`（范围与成功标准） |
| 版本 | v2.0 |
| 阶段 | 第 3–4 周 |
| 架构风格 | 分层 + 端口适配器（轻量） |

## 1. 系统架构

### 1.1 分层

```text
┌─────────────────────────────────────────────────────────────┐
│ 主编排入口  orchestration/run_daily.py · cli.py              │
│   幂等检查 → 采集 → 生成 → 渲染 → 推送 → 写运行摘要          │
└───────┬──────────────────┬──────────────────┬───────────────┘
        │                  │                  │
┌───────▼────────┐ ┌───────▼────────┐ ┌───────▼───────────────┐
│ 采集层          │ │ 生成层          │ │ 推送层                 │
│ collectors/     │ │ generation/     │ │ publishers/            │
│  github         │ │  attribution    │ │  email                 │
│  feishu         │ │  builder        │ │  feishu_bot            │
│  mock           │ │ render/         │ │  fake                  │
└───────┬────────┘ └───────┬────────┘ └───────┬───────────────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                  ┌────────▼────────┐
                  │ 共享基础层        │
                  │ models · errors  │
                  │ config · storage │
                  └─────────────────┘
```

**依赖方向约束**：采集层、生成层、推送层只依赖共享基础层；只有 `orchestration/` 可以同时依赖三者。任何下层模块反向 import 上层视为分层违规，在 `tests/test_architecture.py` 中检查。

### 1.2 模块职责（一句话边界）

| 模块 | 职责边界 |
|---|---|
| `config.py` | 从环境变量装配全部配置；不读文件、不访问网络 |
| `models.py` | 全部领域数据结构；无业务逻辑、无 IO |
| `errors.py` | 异常类型与错误码；不含处理策略 |
| `net.py` | HTTP 调用的统一超时与按异常类型分流的重试；实现 ADR-003 |
| `storage/schema.py` | 建表 DDL 与幂等初始化 |
| `storage/repository.py` | 原始记录与日报的持久化、查询；仅此模块写 SQL |
| `collectors/base.py` | 采集端口 `Protocol` 定义与结果类型 |
| `collectors/github.py` | GitHub REST 采集实现；只产出 `CommitRecord` |
| `collectors/feishu.py` | 飞书任务 / 消息采集实现；只产出对应记录 |
| `collectors/mock.py` | 离线演示数据源；与真实实现同契约 |
| `generation/attribution.py` | 原始记录 → 成员归组；缺失映射不猜测 |
| `generation/builder.py` | 归组结果 → `DailyReport`（个人 / 团队） |
| `render/text.py` | `DailyReport` → 纯文本 / HTML；不做数据加工 |
| `publishers/*` | 把渲染结果投递到渠道，返回结构化结果；不生成内容 |
| `orchestration/run_daily.py` | 串联全流程并保证幂等；唯一可跨层调用的模块 |
| `cli.py` | 命令行参数解析与进程退出码 |

## 2. 数据模型

### 2.1 领域结构（`models.py`）

```python
class ReportScope(str, Enum):
    PERSONAL = "personal"
    TEAM = "team"

@dataclass(frozen=True)
class Member:
    member_id: str
    name: str
    github_login: str | None = None
    feishu_open_id: str | None = None
    email: str | None = None

@dataclass(frozen=True)
class CommitRecord:
    sha: str
    author_login: str
    message: str
    committed_at: datetime          # 必须为 UTC aware
    repo: str

@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    title: str
    status: str
    assignee_open_id: str | None
    updated_at: datetime            # UTC

@dataclass(frozen=True)
class MessageRecord:
    msg_id: str
    sender_open_id: str | None
    content: str
    created_at: datetime            # UTC
    chat_id: str
    is_recalled: bool = False

@dataclass(frozen=True)
class ReportItem:
    source_type: str                # "github" | "feishu_task" | "feishu_message"
    source_id: str                  # 非空，可追溯约束
    text: str
    occurred_at: datetime           # UTC

@dataclass
class DailyReport:
    scope: ReportScope              # 必填，无默认值
    entity_id: str
    report_date: date
    items: list[ReportItem]
    generated_at: datetime
    note: str | None = None         # "无数据" / "来源缺失：github" 等
```

### 2.2 SQLite 表结构（`storage/schema.py`）

| 表 | 关键列 | 约束 |
|---|---|---|
| `members` | `member_id PK`, `name`, `github_login`, `feishu_open_id`, `email` | `member_id` 唯一 |
| `commit_records` | `sha PK`, `author_login`, `message`, `committed_at`, `repo` | 时间存 UTC ISO8601 |
| `task_records` | `task_id PK`, `title`, `status`, `assignee_open_id`, `updated_at` | 同上 |
| `message_records` | `msg_id PK`, `sender_open_id`, `content`, `created_at`, `chat_id`, `is_recalled` | 同上 |
| `daily_reports` | `id PK`, `scope`, `entity_id`, `report_date`, `generated_at`, `body_json`, `note` | `(scope, entity_id, report_date)` 唯一 |
| `run_summaries` | `id PK`, `team_id`, `run_date`, `status`, `collected_json`, `sent_json`, `failed_json`, `started_at`, `finished_at` | `(team_id, run_date)` 成功唯一 |

**存储约束**：
1. 时间一律以 UTC ISO8601 字符串存储。
2. 原始记录表只追加，不更新（`INSERT OR IGNORE` 按主键去重）。
3. 全部 SQL 参数化，禁止字符串拼接。
4. 开启 `PRAGMA foreign_keys=ON`、`journal_mode=WAL`。

## 3. 接口契约

**时间语义统一**：所有 `since` **含**、`until` **不含**，且必须为 UTC aware；传入 naive datetime 抛 `ValueError`。

### 3.1 采集层（端口定义于 `collectors/base.py`）

```python
class CommitSource(Protocol):
    def collect_commits(
        self, owner: str, repo: str,
        since: datetime, until: datetime, *, max_pages: int = 10,
    ) -> list[CommitRecord]: ...

class TaskSource(Protocol):
    def collect_tasks(self, since: datetime, until: datetime) -> list[TaskRecord]: ...

class MessageSource(Protocol):
    def collect_messages(self, since: datetime, until: datetime) -> list[MessageRecord]: ...
```

- 空区间返回 `[]`，不抛异常。
- 达到 `max_pages` 时记录 warning 并返回已取数据（截断可感知）。
- 认证失败抛 `AuthenticationError`；网络/超时抛 `TransientError`。

### 3.2 生成层（`generation/builder.py`）

```python
def generate_report(
    scope: ReportScope,
    entity_id: str,
    report_date: date,
    *,
    members: Sequence[Member],
    commits: Sequence[CommitRecord],
    tasks: Sequence[TaskRecord],
    messages: Sequence[MessageRecord],
    missing_sources: Sequence[str] = (),
    now: datetime | None = None,
) -> DailyReport: ...
```

- `scope` 必填，**无默认值**。
- 无任何记录时返回带 `note="无数据"` 的日报，**不返回 `None`**。
- `PERSONAL` 只包含 `entity_id` 本人数据；`TEAM` 按成员分组后汇总。
- 每条 `ReportItem` 的 `source_id` 必非空，否则抛 `TraceabilityError`。

### 3.3 渲染层（`render/text.py`）

```python
def render_text(report: DailyReport) -> str: ...
def render_email_html(report: DailyReport) -> str: ...
def render_team_text(report: DailyReport) -> str: ...
```

纯函数，无 IO，不修改入参。

### 3.4 推送层（`publishers/base.py`）

```python
@dataclass
class SendResult:
    success: list[str]
    failed: list[tuple[str, str]]     # (收件人, 失败原因)

@dataclass
class PushResult:
    ok: bool
    error: str | None = None

class EmailPublisher(Protocol):
    def send_email(self, report: DailyReport, recipients: Sequence[str]) -> SendResult: ...

class BotPublisher(Protocol):
    def push_to_feishu(self, report: DailyReport, webhook: str) -> PushResult: ...
```

- `send_email` 单收件人失败**不中断**整批，全部失败时 `failed` 覆盖全部收件人。
- 收件人邮箱在日志中脱敏为 `a***@example.com`。

### 3.5 主编排入口（`orchestration/run_daily.py`）

```python
def run_daily(
    team_id: str,
    report_date: date,
    *,
    settings: Settings,
    repo: Repository,
    sources: SourceBundle,
    publishers: PublisherBundle,
    now: datetime | None = None,
) -> RunSummary: ...
```

- 幂等：同日同团队已有 `status="success"` 的运行则直接返回该摘要，不重复采集与推送。
- 单源失败：记录到 `RunSummary.failed`，其余继续。
- 编排层串行调用，无共享可写文件。

### 3.6 考勤采集（v1.1 变更新增）

```python
class AttendanceSource(Protocol):
    def collect_attendance(
        self, since: datetime, until: datetime
    ) -> list[AttendanceRecord]: ...

@dataclass(frozen=True)
class AttendanceRecord:
    record_id: str                    # 非空，可追溯
    member_open_id: str | None
    work_date: date
    status: str                       # present | absent | late | leave
    checked_in_at: datetime | None    # UTC
    checked_out_at: datetime | None   # UTC
```

- ``SourceBundle`` 增加可选字段 ``attendance_source: AttendanceSource | None = None``：未配置时行为与变更前完全一致（向后兼容）。
- ``generate_report`` 增加关键字参数 ``attendance: Sequence[AttendanceRecord] = ()``，默认空。
- 考勤条目 ``source_type="feishu_attendance"``，文本按 ``status`` 渲染：
  ``present`` → ``考勤：出勤 HH:MM``；``absent`` → ``考勤：缺勤``；``late`` → ``考勤：迟到 HH:MM``；``leave`` → ``考勤：请假``。
- 条目插入位置由 ``Settings.attendance_position`` 决定（``"after_commits"`` | ``"end"``，默认 ``"end"``）。

## 4. 技术选型 ADR

### ADR-001　HTTP 客户端选型

| 项 | 内容 |
|---|---|
| 状态 | 已采纳 |
| 背景 | 需要访问 GitHub REST 与飞书开放平台，需统一超时、重试与测试替身 |
| 备选项 | ① `requests`；② 标准库 `urllib`；③ `httpx` |
| 决策 | `httpx` |
| 理由 | 原生同步/异步双接口，`timeout` 为一等参数；`httpx.MockTransport` 可直接注入测试响应，无需 monkeypatch 网络栈。`requests` 生态成熟但测试替身需额外依赖；`urllib` 需自行处理连接池与超时细节，代码量最大 |

### ADR-002　存储选型

| 项 | 内容 |
|---|---|
| 状态 | 已采纳 |
| 背景 | 单团队、单机部署，日报历史 ≥ 90 天，日增量在千条量级 |
| 备选项 | ① 标准库 `sqlite3`；② SQLAlchemy + Alembic；③ JSON 文件 |
| 决策 | 标准库 `sqlite3` + 手写参数化 SQL |
| 理由 | 数据量远低于 SQLite 上限；零额外依赖，部署即复制文件；显式 SQL 便于逐条审查参数化（NFR-S4）。JSON 文件无法支持按日期/成员查询与并发写。ORM 在本规模引入抽象成本，且现场答辩时 SQL 可见性更重要 |

### ADR-003　重试策略

| 项 | 内容 |
|---|---|
| 状态 | 已采纳 |
| 背景 | 外部 API 存在限流与瞬时超时；认证失败重试无意义且会延长故障 |
| 备选项 | ① 全部统一重试；② 不重试；③ 按异常类型分流 |
| 决策 | 按异常类型分流：`TransientError`（超时、5xx、429）最多重试 2 次，退避 1s/2s；`AuthenticationError` 不重试 |
| 理由 | 统一重试会把 401 放大成 3 倍无效请求；不重试则瞬时抖动直接造成来源缺失。分流以最小代价覆盖两类真实故障 |

### ADR-004　数据源与推送渠道的端口适配器

| 项 | 内容 |
|---|---|
| 状态 | 已采纳 |
| 背景 | 课程第 0 周的飞书凭证与 SMTP 授权码可能未就绪；演示与测试不得依赖真实外部系统 |
| 备选项 | ① 真实实现内嵌 `if mock` 分支；② 端口 + 双实现；③ 只做 Mock |
| 决策 | 端口 + 真实/Mock 双实现，由 `Settings.source_mode` 切换 |
| 理由 | 内嵌分支会让真实与模拟逻辑互相污染，无法独立测试；只做 Mock 则交付物不完整。双实现共享同一 `Protocol`，测试可直接注入替身，配置一行即可切换（对应指导书 FAQ“数据源可替换”要求） |

### ADR-005　考勤数据源的接入方式

| 项 | 内容 |
|---|---|
| 状态 | 已采纳（v1.1 变更） |
| 背景 | 需要在已有四层结构上接入第四类数据源，且不得破坏既有三源流程 |
| 备选项 | ① 修改既有 `collect_tasks` 签名塞入考勤；② 新增独立 Protocol；③ 在生成层直接读库 |
| 决策 | 新增独立 `AttendanceSource` Protocol，`SourceBundle` 增加可选字段 |
| 理由 | ① 会让任务采集承担两种语义，违反单一职责；③ 让生成层绕过采集层，破坏分层。② 与既有端口模式一致，可选字段保证未配置时零影响；实现只需改一个装配点 |

## 5. 非功能性约束

| 编号 | 约束 | 落地方式 |
|---|---|---|
| NFR-P1 | 单成员生成 ≤ 2 秒（≤ 500 条记录） | 单次遍历归组，O(n) |
| NFR-P2 | 全流程 ≤ 5 分钟（≤ 10 人） | 串行调用 + 单接口超时 10 秒 |
| NFR-S1 | 凭证仅环境变量注入 | `config.py` 唯一读取点，无默认硬编码 |
| NFR-S2 | GitHub 令牌只读 | 文档与 `.env.example` 注明 scope，不做写操作 |
| NFR-S3 | 日志脱敏 | 日志过滤器替换 token；邮箱脱敏函数 |
| NFR-S4 | SQL 全参数化 | 仅 `repository.py` 写 SQL，code-review 逐条检查 |
| NFR-S5 | 仅采集工作账号 | 采集范围由 `members` 映射限定 |
| NFR-R1 | 单模块失败不中断 | 采集/推送异常在编排层逐项捕获 |
| NFR-R2 | 幂等 | `run_summaries(team_id, run_date, status)` 唯一约束 |
| NFR-R3 | 静态扫描零告警 | `ruff check .` 进 CI |
| NFR-R4 | 契约变更须走审核 | `docs/接口契约变更审核记录.md` |

## 6. 第 4 周变更预留（考勤采集）

设计上预留而不实现：

- 采集层新增 `AttendanceSource` Protocol（`collect_attendance(since, until) -> list[AttendanceRecord]`）。
- `ReportItem.source_type` 增加 `"feishu_attendance"`，生成层按 `source_type` 排序插入位置由配置决定。
- `daily_reports.body_json` 结构不变，新增条目自动容纳，无需迁移。
- 幂等键不变，因为考勤属于同一运行批次。

上述变更在第 4 周按 `proposal → design → tasks → 代码 → 回归` 顺序落地，变更前后均记录在 `docs/变更涟漪演练记录.md`。