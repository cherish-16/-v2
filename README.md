# 智能日报生成器 v2

> 从团队成员的**真实工作数据**（GitHub 提交、飞书任务、飞书群消息、飞书考勤）自动生成个人与团队日报，经邮件与飞书机器人推送，并用 SQLite 保存历史。

本项目是《软件工程职业技能实践》课程设计阶段二（第 3–4 周）的交付物，采用 **Superpowers 工作流驱动**从零实现，遵循规范驱动开发（SDD）：规范先行、测试先行、小步提交、评审留痕。

## 功能范围

| 编号 | 功能 | 状态 |
|---|---|---|
| R-01 | 采集 GitHub 提交记录（UTC 日区间、只读令牌、分页上限） | 已实现 |
| R-02 | 采集飞书任务流转 | 已实现 |
| R-03 | 采集飞书群消息（撤回消息保留并标注） | 已实现 |
| R-04 | 生成个人日报（含无数据日标注、来源可追溯） | 已实现 |
| R-05 | 生成团队日报（按成员归组、格式统一、缺失成员标注） | 已实现 |
| R-06 | 邮件推送（部分失败隔离，返回结构化结果） | 已实现 |
| R-07 | 飞书机器人推送 | 已实现 |
| R-08 | SQLite 存储与查询日报历史 | 已实现 |
| R-09 | 成员与采集映射配置 | 已实现 |
| R-10 | 定时触发全流程并保证幂等 | 已实现 |
| R-11 | 采集飞书考勤数据并纳入日报（v1.1 变更） | 已实现 |

明确不做：AI 智能摘要、Web 管理界面、多租户、移动端（详见 `specs/proposal.md`）。

## 技术栈

- Python 3.12+，依赖管理 `uv`
- HTTP 客户端 `httpx`（统一超时与重试）
- 存储：SQLite（标准库 `sqlite3`，参数化查询）
- 测试：`pytest` / `pytest-cov`；静态扫描：`ruff`
- 凭证：仅环境变量注入，禁止入库

## 快速开始

```bash
# 1. 安装依赖
uv sync --dev

# 2. 生成配置文件模板并填写（mock 模式无需任何凭证）
cp .env.example .env

# 3. 离线演示：使用内置演示数据，无需外部凭证
uv run python -m daily_report run --team demo --demo --print
```

`--demo` 会使用内置的 Mock 数据源，适合课堂演示与首次验证。

## 配置（环境变量）

见 [.env.example](.env.example)，主要项：

| 变量 | 说明 |
|---|---|
| `DAILY_REPORT_SOURCE_MODE` | `mock`（默认，离线演示）或 `live`（调用真实 API） |
| `DAILY_REPORT_TIMEZONE` | 团队时区，默认 `Asia/Shanghai` |
| `GITHUB_TOKEN` | GitHub 只读令牌 |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 飞书自建应用凭证 |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | 邮件推送（密码为授权码） |
| `FEISHU_BOT_WEBHOOK` | 飞书群机器人 webhook |

> 密钥一律通过环境变量注入；硬编码令牌按红线处理。

## 命令行用法

```bash
# 导入成员映射（JSON）
uv run python -m daily_report members import --file members.json --db daily_report.db

# 查看已配置成员
uv run python -m daily_report members list --db daily_report.db

# 生成并推送指定日期的日报
uv run python -m daily_report run --team <team_id> --date 2026-11-26

# 仅打印日报正文，不推送
uv run python -m daily_report run --team <team_id> --print
```

退出码：`0` 成功或重复触发被忽略；`2` 参数错误。

## 测试与质量门禁

```bash
uv run pytest                 # 全部测试
uv run pytest --cov=src       # 覆盖率
uv run ruff check src tests   # 静态扫描（要求零告警）
```

测试遵循 TDD 红绿循环：先写失败测试，再实现，最后重构。

## 架构

四层结构，依赖方向自上而下，编排层是唯一可同时依赖各层的入口：

```text
采集层 collectors/  →  生成层 generation/  →  推送层 publishers/  →  编排入口 orchestration/
                         ↑ 数据模型 models.py / 存储 storage/
```

```text
src/daily_report/
├── collectors/      # GitHub / 飞书 / Mock 数据源
├── generation/      # 归组与日报构建（个人 / 团队）
├── publishers/      # 邮件 / 飞书机器人 / Fake
├── render/          # 日报渲染
├── storage/         # SQLite 仓储与表结构
├── orchestration/   # run_daily 全流程编排
├── models.py        # 数据实体
├── config.py        # 环境变量配置
├── members.py       # 成员映射
├── net.py           # HTTP 超时与重试
└── cli.py           # 命令行入口
```

架构约束由 `tests/test_architecture.py` 守护。

## 规范与文档

| 位置 | 内容 |
|---|---|
| [specs/proposal.md](specs/proposal.md) | 需求与范围（做什么 / 不做什么 / 可度量目标） |
| [specs/design.md](specs/design.md) | 系统架构、数据模型、接口契约、ADR |
| [specs/tasks.md](specs/tasks.md) | 任务分解与验收标准 |
| `docs/` | 需求分析、用例图、变更审核、code-review、一致性检查、规范审计、回归测试、总结报告、AI 使用声明等过程文档 |
| `docs/uml/` | PlantUML 用例图与业务流程图源文件 |
| `docs/superpowers/plans/` | 工作流计划记录 |

规范即事实来源：**代码与规范冲突时，要么改代码，要么走规范变更流程**（SDD 原则⑤）。规范守护由 `scripts/check_spec_drift.py` 与自检记录保障。

## 工作流纪律

- 规范先行：先更新 `specs/`，再写代码
- TDD：测试先于实现
- 小步提交：一次提交对应一个可验证交付物，格式 `feat|fix|test|docs: [任务编号] 说明`
- 合并前必须走 code-review，评审意见逐条回应或修复
- 密钥仅环境变量；日志脱敏

## 分支说明

- `feature`：当前开发分支（本仓库主交付分支）
- `main`：初始仓库骨架，未合并本分支工作

## 许可

课程设计项目，仅供学习与评审使用。
# 智能日报 v2

> 智能日报系统 —— 软件工程职业技能实践课程设计

## 项目简介

本项目为课程设计项目，用于实现「智能日报」系统。

（待补充：项目背景、目标与核心功能）

## 技术栈

（待补充）

## 目录结构

```
.
├── README.md
└── .gitignore
```

## 快速开始

（待补充：环境要求、安装依赖、启动方式）

## 分支约定

| 分支 | 用途 |
| --- | --- |
| `main` | 主干分支，保持可运行 |
| `feature/*` | 功能开发分支 |
| `fix/*` | 缺陷修复分支 |

## 提交信息约定

采用 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/)：

```
<类型>(<范围>): <描述>
```

常用类型：`feat` 新功能、`fix` 修复、`docs` 文档、`style` 格式、`refactor` 重构、`test` 测试、`chore` 构建/工具。

## 许可证

（待补充）
