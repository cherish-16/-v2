# 设计与 specs/ 一致性检查记录

| 项目 | 内容 |
|---|---|
| 项目名称 | 智能日报生成器（v2 · Superpowers 工作流驱动） |
| 所处阶段 | 阶段二（第 3–4 周） |
| 所属周次 | 第 3 周 |
| 记录角色 | 架构师 |
| 检查对象 | `specs/design.md` ↔ `specs/proposal.md` ↔ `specs/tasks.md` ↔ v2 源码 |
| 检查方法 | 逐条对照：设计条目 → spec 原文位置 → 代码实现位置 → 结论；不一致即登记缺陷 |
| 检查日期 | 2026-11-20 |
| 文档版本 | v1.0 |

> 依据 SDD 原则⑤“代码服务规范”：代码与规范冲突时，要么改代码，要么走规范变更流程，**不允许悄悄不一致**。本记录是 v2 阶段的规范守护自检证据。

## 1. 检查范围与判定标准

| 检查项 | 判定标准 |
|---|---|
| 接口契约一致性 | `design.md` 中的函数签名 / 参数 / 返回类型 / 异常语义与代码逐字一致 |
| 数据模型一致性 | `design.md` 的实体字段、类型、必填约束与 SQLite 表结构、代码 dataclass 一致 |
| 任务覆盖一致性 | `tasks.md` 每条任务的验收标准在代码与测试中可找到对应实现 |
| 分层职责一致性 | 采集 / 生成 / 推送 / 编排四层的依赖方向与 `design.md` 架构图一致 |
| ADR 约束一致性 | 技术选型（HTTP 客户端、SQLite、重试策略、密钥管理）与 ADR-001~003 结论一致 |
| 范围一致性 | 实现功能均在 `proposal.md` 范围内，无“范围外功能”混入 |
| 非功能性约束 | 采集频率限制、密钥环境变量注入、异常重试均有对应实现或配置 |

## 2. 一致性对照表

### 2.1 接口契约

| 设计条目（`design.md` §4） | 代码位置 | 一致性 | 备注 |
|---|---|---|---|
| `collect_commits(owner, repo, since, until, *, max_pages)` → `list[CommitRecord]` | `collectors/github_collector.py:38` | 一致 | 含/不含语义已在 docstring 标注 |
| `collect_tasks(since, until)` → `list[TaskRecord]` | `collectors/feishu_collector.py:24` | 一致 | CR-004 已驳回分页外露 |
| `collect_messages(since, until)` → `list[MessageRecord]` | `collectors/feishu_collector.py:71` | 一致 | — |
| `generate_report(scope, entity_id, report_date)` → `DailyReport` | `report/generator.py:29` | 一致 | `scope` 必填，CR-002 已整改 |
| `render_email(report)` → `str`（HTML） | `renderers/email_renderer.py:18` | 一致 | — |
| `send_email(report, recipients)` → `SendResult` | `pushers/email_pusher.py:41` | 一致 | CR-003 |
| `push_to_feishu(report, webhook)` → `PushResult` | `pushers/feishu_pusher.py:33` | 一致 | — |
| `run_daily(team_id, report_date)` → `RunSummary` | `main.py:57`（编排入口） | 一致 | 串行编排，无共享写冲突 |

### 2.2 数据模型

| 设计实体（`design.md` §3） | SQLite 表 / 代码结构 | 字段一致性 | 结论 |
|---|---|---|---|
| `Member` | `members` 表 / `models.py:Member` | id、name、feishu_id、github_login 一致 | 一致 |
| `CommitRecord` | `models.py:CommitRecord` | sha、author、message、committed_at(UTC) 一致 | 一致 |
| `TaskRecord` | `models.py:TaskRecord` | task_id、title、status、assignee、updated_at 一致 | 一致 |
| `MessageRecord` | `models.py:MessageRecord` | msg_id、sender、content、created_at 一致 | 一致 |
| `DailyReport` | `models.py:DailyReport` | scope、entity_id、date、items、generated_at 一致 | 一致 |
| `RunSummary` | `models.py:RunSummary` | collected、generated、sent、failed 一致 | 一致 |

### 2.3 任务覆盖与分层职责

| `tasks.md` 任务 | 验收标准在测试中的对应 | 分层依赖检查 | 结论 |
|---|---|---|---|
| T2-01 GitHub 采集 | `test_github_collector.py` 全部用例 | 仅依赖 `models`，未反向依赖上层 | 一致 |
| T2-02 飞书任务/消息采集 | `test_feishu_tasks.py`、`test_feishu_messages.py` | 同上 | 一致 |
| T2-03 日报生成 | `test_generator.py` | 依赖采集产物模型，不直接调用采集器 | 一致 |
| T2-04 邮件推送 | `test_email_pusher.py` | 依赖 `renderers` 与 `models` | 一致 |
| T2-05 飞书机器人推送 | `test_feishu_pusher.py` | 依赖 `models` | 一致 |
| T2-06 主编排入口 | `test_main.py`（集成） | 仅编排层可同时依赖四层 | 一致 |

### 2.4 ADR 与非功能性约束

| ADR / 约束 | 要求 | 实现核查 | 结论 |
|---|---|---|---|
| ADR-001 HTTP 客户端 | 统一使用 `httpx`，设置超时 | 全部采集器使用 `httpx.Client(timeout=...)` | 一致 |
| ADR-002 存储 | SQLite（标准库 `sqlite3`），语句参数化 | 无字符串拼接 SQL | 一致 |
| ADR-003 重试 | 网络/超时类最多重试 2 次，认证类不重试 | `pushers`、`collectors` 均按异常类型分流 | 一致 |
| 密钥管理 | 令牌仅从环境变量读取，禁止入库入仓 | 全仓检索无硬编码令牌 | 一致 |
| 采集频率限制 | 采集间隔与分页上限可配置 | `config.py` 提供上限参数 | 一致 |
| 日志脱敏 | 不打印令牌、邮箱全量 | 邮箱已脱敏（RV-003/R3-01） | 一致 |

## 3. 不一致项清单与整改

| 编号 | 不一致描述 | 类别 | 严重度 | 处理方式 | 负责人 | 状态 |
|---|---|---|---|---|---|---|
| DI-001 | `design.md` 写 `DailyReport` 含 `scope`，代码初版缺该字段 | 数据模型 | 严重 | 改代码，已补字段 | 开发工程师 | 已关闭 |
| DI-002 | `design.md` 约定 GitHub 采集 UTC，代码使用本地时间 | 接口契约 | 严重 | 改代码（关联 CR-001、RV-001/R1-01） | 开发工程师 | 已关闭 |
| DI-003 | `tasks.md` T2-04 要求“部分失败继续”，代码初版抛异常中断 | 任务覆盖 | 严重 | 改代码 + 走契约变更 CR-003 | 开发工程师 | 已关闭 |
| DI-004 | `proposal.md` 未列“飞书机器人推送”，代码已实现 | 范围 | 一般 | 更新 `proposal.md` 范围条目（属更正性补充，不扩大范围） | 需求分析师 | 已关闭 |
| DI-005 | `design.md` 未约定“空数据日”行为 | 规范缺失 | 一般 | 走契约变更 CR-002 补规范，代码按规范实现 | 架构师 | 已关闭 |
| DI-006 | 团队日报归组规则实现为按提交拼接 | 业务逻辑 / 规范 | 严重 | 改代码（RV-002/R2-02） | 开发工程师 | 已关闭 |

> 处理原则：**规范正确则改代码；代码先行的合理实现则走规范变更流程补规范**。两类处理均须在本记录中留痕。

## 4. 复检结果

| 检查轮次 | 日期 | 不一致项数 | 已关闭 | 遗留 | 复检结论 |
|---|---|---|---|---|---|
| 第 1 轮（初检） | 2026-11-19 | 6 | 4 | 2 | 需整改 |
| 第 2 轮（复检） | 2026-11-20 | 0 | 0 | 0 | 通过 |

- [x] 接口契约逐条对照无差异
- [x] 数据模型字段 / 类型 / 约束一致
- [x] `tasks.md` 每条任务均有可追溯的实现与测试
- [x] 分层依赖方向符合架构图，无跨层反向依赖
- [x] ADR-001~003 约束均落实到代码或配置
- [x] 实现功能未超出 `proposal.md` 范围
- [x] 全仓无硬编码密钥，日志无敏感信息

## 5. 结论与签署

v2 第 3 周设计与 `specs/` 已达到逐条一致，6 项不一致全部关闭，可作为第 4 周“变更涟漪演练”的对照基线。建议在第 4 周收到“考勤采集”需求变更时，沿用本记录方法：先改 `proposal → design → tasks`，再改代码，最后回归本表。

| 角色 | 姓名 | 日期 |
|---|---|---|
| 架构师（检查与签署） |  |  |
| 开发工程师（代码侧确认） |  |  |
| 需求分析师（范围与任务侧确认） |  |  |
| 配置管理员（规范入库版本确认） |  |  |
