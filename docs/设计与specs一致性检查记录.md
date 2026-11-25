# 设计与 specs/ 一致性检查记录

| 项目 | 内容 |
|---|---|
| 项目名称 | 智能日报生成器（v2 · Superpowers 工作流驱动） |
| 所处阶段 | 阶段二（第 3–4 周） |
| 所属周次 | 第 3 周 |
| 记录角色 | 架构师 |
| 检查对象 | `specs/design.md` ↔ `specs/proposal.md` ↔ `specs/tasks.md` ↔ v2 源码 |
| 检查方法 | 逐条对照：设计条目 → spec 原文位置 → 代码实现位置 → 结论；不一致即登记缺陷 |
| 检查日期 | 2026-11-25 |
| 文档版本 | v2.0（按实际实现重写） |

> 依据 SDD 原则⑤“代码服务规范”：代码与规范冲突时，要么改代码，要么走规范变更流程，**不允许悄悄不一致**。
>
> **本版说明**：v1.0 版本描述的代码与提交在本仓库中并不存在（`specs/` 缺失、全仓无 `.py`、文中引用的 `abc1234` 等提交号查无此物）。本版按实际落地代码重写，所有“代码位置”均指向真实文件与行号，可用 `git log --oneline` 复核。

## 1. 检查范围与判定标准

| 检查项 | 判定标准 | 自动检查方式 |
|---|---|---|
| 接口契约一致性 | `design.md` 的函数签名 / 参数 / 返回类型与代码一致 | 人工逐条对照 |
| 数据模型一致性 | `design.md` 实体字段、类型、约束与 dataclass、SQLite 表一致 | 人工逐条对照 |
| 任务覆盖一致性 | `tasks.md` 每条任务的验收标准在测试中有对应用例 | 测试文件对照 |
| 分层职责一致性 | 采集 / 生成 / 推送 / 渲染 / 存储不得反向依赖编排层 | `tests/test_architecture.py` |
| ADR 约束一致性 | ADR-001~004 的结论落实到代码或配置 | 人工逐条对照 |
| 范围一致性 | 实现功能均在 `proposal.md` 范围内 | `tests/test_regression.py`（第 4 周） |
| 非功能性约束 | 密钥环境变量注入、参数化 SQL、日志脱敏 | `test_config.py`、`test_architecture.py`、`test_email_pusher.py` |
| SQL 集中性 | 除 `storage/` 外任何模块不含 SQL 字面量 | `tests/test_architecture.py` |

## 2. 一致性对照表

### 2.1 接口契约

| 设计条目（`design.md`） | 代码位置 | 一致性 | 备注 |
|---|---|---|---|
| `collect_commits(owner, repo, since, until, *, max_pages)` → `list[CommitRecord]` | `src/daily_report/collectors/github.py:34` | 一致 | 含/不含语义在 docstring 标注 |
| `collect_tasks(since, until)` → `list[TaskRecord]` | `src/daily_report/collectors/feishu.py:60` | 一致 | 分页在内部完成，未外露（CR-004 结论） |
| `collect_messages(since, until)` → `list[MessageRecord]` | `src/daily_report/collectors/feishu.py:109` | 一致 | 撤回消息置 `is_recalled=True` |
| `generate_report(scope, entity_id, report_date, *, ...)` → `DailyReport` | `src/daily_report/generation/builder.py:91` | 一致 | `scope` 无默认值（CR-002 整改项一） |
| `render_text / render_email_html / render_team_text` | `src/daily_report/render/text.py:26/33/52` | 一致 | 纯函数，测试含深比较断言 |
| `send_email(report, recipients)` → `SendResult` | `src/daily_report/publishers/email.py:44` | 一致 | 单封失败不中断（CR-003） |
| `push_to_feishu(report, webhook=None)` → `PushResult` | `src/daily_report/publishers/feishu_bot.py:25` | 一致 | 业务错误码 `code != 0` 转失败 |
| `run_daily(team_id, report_date, *, settings, repo, sources, publishers, now)` → `RunSummary` | `src/daily_report/orchestration/run_daily.py:42` | 一致 | 串行编排，无共享可写文件 |
| `get_json / post_json`（ADR-003 重试分流） | `src/daily_report/net.py:76/96` | 一致 | 401/403 不重试；429/5xx/超时重试 2 次 |

### 2.2 数据模型

| 设计实体（`design.md` §2.1） | 代码位置 | 字段一致性 | 结论 |
|---|---|---|---|
| `Member` | `models.py:31` | member_id、name、github_login、feishu_open_id、email | 一致 |
| `CommitRecord` | `models.py:40` | sha、author_login、message、committed_at(UTC)、repo | 一致 |
| `TaskRecord` | `models.py:52` | task_id、title、status、assignee_open_id、updated_at | 一致 |
| `MessageRecord` | `models.py:64` | msg_id、sender_open_id、content、created_at、chat_id、is_recalled | 一致 |
| `ReportItem` | `models.py:77` | source_type、source_id（非空校验）、text、occurred_at | 一致 |
| `DailyReport` | `models.py:90` | scope、entity_id、report_date、items、generated_at、note | 一致 |
| `RunSummary` | `models.py:103` | 全部字段 + status 取值校验 | 一致 |

### 2.3 表结构

| 设计表（`design.md` §2.2） | 代码位置 | 约束核查 | 结论 |
|---|---|---|---|
| `members` | `storage/schema.py:11` | `member_id` 主键 | 一致 |
| `commit_records` | `storage/schema.py:19` | `sha` 主键去重 | 一致 |
| `task_records` | `storage/schema.py:27` | `task_id` 主键 | 一致 |
| `message_records` | `storage/schema.py:35` | `msg_id` 主键 + `is_recalled` | 一致 |
| `daily_reports` | `storage/schema.py:44` | `UNIQUE(scope, entity_id, report_date)` | 一致 |
| `run_summaries` | `storage/schema.py:55` | 部分唯一索引 `(team_id, run_date) WHERE status='success'` | 一致（实现幂等） |

### 2.4 任务覆盖与分层职责

| `tasks.md` 任务 | 对应测试文件 | 用例数 | 结论 |
|---|---|---|---|
| T3-01/T3-02 骨架与模型 | `test_models.py`、`test_errors.py` | 9 | 一致 |
| T3-03 配置 | `test_config.py` | 5 | 一致 |
| T3-04 存储 | `test_storage.py` | 7 | 一致 |
| T3-05 网络助手 | `test_net.py` | 6 | 一致 |
| T3-06 端口与 Mock | `test_collectors_base.py` | 5 | 一致 |
| T3-07 GitHub 采集 | `test_github_collector.py` | 6 | 一致 |
| T3-08 飞书采集 | `test_feishu_collector.py` | 5 | 一致 |
| T3-09 归属 | `test_attribution.py` | 5 | 一致 |
| T3-10 个人日报 | `test_builder_personal.py` | 7 | 一致 |
| T3-11 团队日报 | `test_builder_team.py` | 5 | 一致 |
| T3-12 渲染 | `test_render.py` | 5 | 一致 |
| T3-13 邮件 | `test_email_pusher.py` | 5 | 一致 |
| T3-14 飞书机器人 | `test_feishu_bot.py` | 4 | 一致 |
| T3-15 编排 | `test_run_daily.py` | 5 | 一致 |
| T3-16 CLI | `test_cli.py` | 4 | 一致 |
| T3-17 集成与分层 | `test_integration.py`、`test_architecture.py` | 4 | 一致 |

### 2.5 ADR 与非功能性约束

| ADR / 约束 | 要求 | 实现核查 | 结论 |
|---|---|---|---|
| ADR-001 HTTP 客户端 | 统一 `httpx`，显式超时 | `net.py:21` `DEFAULT_TIMEOUT=10.0`，所有请求经 `net` | 一致 |
| ADR-002 存储 | `sqlite3`，全参数化 | `repository.py` 全部 `?` 占位；`test_architecture.py` 检查 SQL 只在 storage | 一致 |
| ADR-003 重试 | 按异常类型分流，最多 2 次 | `net.py:25` `_classify`；`test_net.py` 覆盖 6 种路径 | 一致 |
| ADR-004 端口适配器 | 真实/Mock 双实现，配置切换 | `config.py:50` `load_settings`；`collectors/mock.py` | 一致 |
| NFR-S1 密钥注入 | 仅环境变量 | `config.py:35` `Settings` / `config.py:50` `load_settings`；`test_config.py` 断言 repr 不泄露 | 一致 |
| NFR-S3 日志脱敏 | 邮箱脱敏 | `publishers/email.py:21` `mask_email`；失败原因只给异常类型名 | 一致 |
| NFR-S4 SQL 参数化 | 无字符串拼接 | `test_architecture.py::test_sql_only_in_storage_layer` | 一致 |
| NFR-R2 幂等 | 同日同团队一次成功运行 | `storage/schema.py:69` 部分唯一索引；`orchestration/run_daily.py:55` 跳过逻辑 | 一致 |

## 3. 不一致项清单与整改

本轮开发过程中实际发现并修复的问题：

| 编号 | 不一致描述 | 类别 | 严重度 | 处理方式 | 状态 |
|---|---|---|---|---|---|
| DI-001 | Mock 采集器在无数据时不校验窗口，naive datetime 静默通过 | 边界条件 | 严重 | 改代码：`_check_window` 在过滤前无条件校验 | 已关闭 |
| DI-002 | GitHub 采集短页未停止，会多发无用请求 | 效率 | 一般 | 改代码：短页即停止 | 已关闭 |
| DI-003 | 计划中的分页截断测试数据只有 1 条，永远到不了第 2 页 | 测试有效性 | 严重 | 改测试：满页 × max_pages | 已关闭 |
| DI-004 | 飞书测试数据时间戳为 2025 年，落在 2026 窗口外 | 测试有效性 | 一般 | 改测试数据为 `1795600800000` | 已关闭 |
| DI-005 | Windows 缺少 tzdata，`ZoneInfo("Asia/Shanghai")` 抛异常 | 运行环境 | 严重 | 加 `tzdata` 依赖 | 已关闭 |
| DI-006 | 计划断言一次运行只产生 1 份日报，实际为个人+团队共 2 份 | 测试有效性 | 一般 | 改断言为“重复运行不新增” | 已关闭 |

> 处理原则：**规范正确则改代码；测试未表达规范意图则改测试**。两类处理均须在此留痕。

## 4. 复检结果

| 检查轮次 | 日期 | 不一致项数 | 已关闭 | 遗留 | 复检结论 |
|---|---|---|---|---|---|
| 第 1 轮（开发中逐任务） | 2026-11-25 | 6 | 6 | 0 | 逐项修复 |
| 第 2 轮（全量复检） | 2026-11-25 | 0 | 0 | 0 | 通过 |

- [x] 接口契约逐条对照无差异
- [x] 数据模型字段 / 类型 / 约束一致
- [x] `tasks.md` 每条任务均有可追溯的实现与测试
- [x] 分层依赖方向符合架构图（`test_architecture.py` 自动化检查）
- [x] ADR-001~004 约束均落实到代码或配置
- [x] 实现功能未超出 `proposal.md` 范围
- [x] 全仓无硬编码密钥，日志无敏感信息

### 实测质量数据

| 指标 | 数值 | 获取方式 |
|---|---|---|
| 测试用例数 | 87 passed | `.venv/Scripts/python.exe -m pytest -q` |
| 测试覆盖率 | 93% | `pytest --cov=daily_report --cov-report=term-missing` |
| 静态扫描 | 0 告警 | `.venv/Scripts/ruff.exe check .` |
| 源码行数 | 1887 行 | `find src -name "*.py" \| xargs wc -l` |
| 提交数（第 3 周） | 16 | `git log --oneline 11e5a8e..HEAD` |

## 5. 结论与签署

v2 第 3 周设计与 `specs/` 已达到逐条一致，6 项不一致全部关闭，可作为第 4 周“变更涟漪演练”的对照基线。

| 角色 | 姓名 | 日期 |
|---|---|---|
| 架构师（检查与签署） |  |  |
| 开发工程师（代码侧确认） |  |  |
| 需求分析师（范围与任务侧确认） |  |  |
| 配置管理员（规范入库版本确认） |  |  |