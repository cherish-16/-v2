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

| 类别 | 选型 | 说明 |
|---|---|---|
| 语言 | Python ≥ 3.12 | 使用 `StrEnum`、`datetime.UTC`、`zoneinfo` 等标准库特性 |
| 依赖管理 | uv（`uv.lock` 锁定） | `uv sync --dev` 一次装齐运行期与开发依赖 |
| HTTP | httpx ≥ 0.27 | 统一 10s 超时，按状态码分流重试（`net.py`，ADR-003） |
| 存储 | SQLite（标准库 `sqlite3`） | 单文件零运维；WAL；全部参数化 SQL，`storage/repository.py` 是唯一写库点 |
| 时区 | 标准库 `zoneinfo` + `tzdata` | 全量存 UTC，按团队时区换算“某一天”的采集窗口 |
| 命令行 | 标准库 `argparse` | `members import/list` 与 `run` 两个子命令 |
| 邮件 | 标准库 `smtplib`（SMTP_SSL） | 逐收件人发送、失败隔离、邮箱脱敏 |
| 飞书 | 开放平台 REST + 群机器人 webhook | 任务 / 消息 / 考勤采集，tenant token 实例内缓存 |
| 配置 | 环境变量 + 自解析 `.env` | 只覆盖 `KEY=VALUE` 子集，不引入 python-dotenv；密钥唯一读取点为 `config.py` |
| 测试 | pytest ≥ 8 + pytest-cov | 单元 / 集成 / 架构守护 / 回归四层，130 个用例 |
| 静态检查 | ruff（`E/F/I/UP/B`，行宽 100） | 零告警为合并门槛 |
| 图示 | PlantUML | `docs/uml/*.puml` 为源文件，导出 PNG 嵌入各报告 |

运行期第三方依赖只有 `httpx` 与 `tzdata`，其余能力均来自标准库。

## 快速开始

### 环境要求

| 项 | 要求 |
|---|---|
| 操作系统 | Windows 10/11（批处理 + 任务计划程序）、Linux / macOS（crontab / systemd） |
| Python | ≥ 3.12（`pyproject.toml` 声明；开发环境在 3.13 上验证） |
| 包管理 | uv 0.13+（已在 0.13.7 验证）；不使用 uv 时可用任意 venv + `pip install -e .` |
| 网络 | mock / demo 模式无需外网；live 模式需可访问 GitHub API、飞书开放平台、SMTP 服务器与飞书 webhook |
| 磁盘 | 本地 SQLite 单文件，按 ≥ 90 天历史预留 1 GB |

### 安装依赖

```bash
git clone <repo>
cd diary_report_generator2

# 运行期依赖 + 开发依赖（pytest / pytest-cov / ruff）
uv sync --dev
```

### 启动方式

**1）离线演示：零配置、无需任何凭证**

```bash
uv run python -m daily_report run --team demo --demo --print
```

`--demo` 使用内置的三人演示数据（提交 / 任务 / 消息 / 考勤），会打印 `status`、JSON 摘要与日报正文。同日重复执行返回 `skipped`；加 `--force` 可强制重跑。

**2）mock 模式：自备成员与数据库，验证链路与配置**

```bash
# 复制配置模板（默认 DAILY_REPORT_SOURCE_MODE=mock）
# Windows 命令提示符用：copy .env.example .env
cp .env.example .env

# 导入成员映射并核对缺失字段
uv run python -m daily_report members import --file members.example.json --db daily_report.db
uv run python -m daily_report members list --db daily_report.db

# 生成日报（mock 模式不调用真实 API，采集为空，用于验证流程）
uv run python -m daily_report run --team t1 --print --db daily_report.db
```

**3）live 模式：采集真实数据并推送**

在 `.env` 中填入 `GITHUB_TOKEN`、`FEISHU_APP_ID` / `FEISHU_APP_SECRET`，并把 `DAILY_REPORT_SOURCE_MODE` 改为 `live`，然后：

```bash
uv run python -m daily_report run --team t1 --db daily_report.db
```

只配置了部分渠道时仅推送已配置渠道：邮件需要 `SMTP_*` 齐全，飞书机器人群需要 `FEISHU_BOT_WEBHOOK`。

**4）Windows 一键运行**

双击仓库根目录的 `推送日报.bat`（内部执行 `run --team t1 --force --print --db my.db`，并强制 UTF-8 输出）。

**5）定时任务**

- Windows：任务计划程序 → 创建基本任务 → 每天 18:00 → 启动程序选择 `推送日报.bat`，起始位置设为仓库根目录。
- Linux / macOS：

  ```bash
  0 18 * * * cd /path/to/diary_report_generator2 && uv run python -m daily_report run --team t1 --db daily_report.db >> /var/log/daily_report.log 2>&1
  ```

### 安装自检

```bash
uv run pytest                        # 全量测试
uv run ruff check src tests          # 静态检查（要求零告警）
```

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

| 子命令 | 参数 | 说明 |
|---|---|---|
| `members import` | `--file`（必填）、`--db`（默认 `daily_report.db`） | 从 JSON 导入成员映射 |
| `members list` | `--db` | 列出成员及缺失的映射字段 |
| `run` | `--team`（必填）、`--date YYYY-MM-DD`、`--print`、`--force`、`--demo`、`--db` | 执行一次完整流程；`--date` 缺省为团队时区“今天”，`--print` 打印日报正文，`--force` 忽略当日幂等记录，`--demo` 使用内置演示数据 |

```bash
# 导入成员映射（JSON）
uv run python -m daily_report members import --file members.json --db daily_report.db

# 查看已配置成员（并提示缺失的映射字段）
uv run python -m daily_report members list --db daily_report.db

# 生成并推送指定日期的日报
uv run python -m daily_report run --team <team_id> --date 2026-11-26

# 仅打印日报正文，不推送
uv run python -m daily_report run --team <team_id> --print

# 强制重跑（忽略当日已有成功运行）
uv run python -m daily_report run --team <team_id> --force
```

退出码：

| 退出码 | 含义 |
|---|---|
| 0 | `success` / `partial` / `skipped`（含重复触发被忽略） |
| 1 | 运行失败（`failed`）、`ReportError`、成员文件错误、未配置成员 |
| 2 | 命令行参数错误 |

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

架构约束由 `tests/test_architecture.py` 守护：下层模块不得 import `orchestration`，SQL 只允许出现在 `storage/`。

## 目录结构

```text
diary_report_generator2/
├── .env.example                  # 配置模板（复制为 .env；真实凭证不入库）
├── pyproject.toml                # 依赖声明、pytest / ruff 配置
├── uv.lock                       # 依赖锁定文件
├── members.example.json          # 成员映射样例（members.json 为本机配置，已忽略）
├── 推送日报.bat                  # Windows 一键运行脚本
├── README.md
│
├── src/daily_report/
│   ├── __main__.py               # python -m daily_report 入口
│   ├── cli.py                    # 子命令解析与退出码
│   ├── config.py                 # 环境变量 / .env 装配（密钥唯一读取点）
│   ├── errors.py                 # ReportError 异常体系
│   ├── members.py                # 成员 JSON 加载与校验
│   ├── models.py                 # 领域模型（UTC 归一、可追溯约束）
│   ├── net.py                    # HTTP 超时与按状态码分流重试
│   ├── collectors/               # 采集层：base 端口、github、feishu、mock
│   ├── generation/               # 生成层：attribution 归组、builder 构建
│   ├── render/                   # 渲染层：纯文本 / 邮件 HTML
│   ├── publishers/               # 推送层：base 端口、email、feishu_bot、fake
│   ├── storage/                  # 持久化：schema DDL、repository（唯一写 SQL 处）
│   └── orchestration/            # 编排：run_daily（幂等、失败隔离、摘要落库）
│
├── tests/                        # pytest 用例（单元 / 集成 / 架构守护 / 回归）
├── scripts/
│   ├── check_spec_drift.py       # 规范守护：改 src 未改 specs 时告警
│   └── generate_analysis_report.py
├── specs/                        # 最高约束规范
│   ├── proposal.md               # 范围与成功标准
│   ├── design.md                 # 架构、数据模型、接口契约、ADR
│   └── tasks.md                  # 任务分解与验收标准
├── docs/                         # 过程文档
│   ├── 需求分析报告.md
│   ├── 系统分析报告.md
│   ├── 系统设计报告.md
│   ├── 项目总结报告.md
│   ├── uml/                      # PlantUML 源文件（.puml）与导出 PNG
│   └── superpowers/plans/        # 工作流计划记录
│
└── daily_report.db               # 运行时生成的 SQLite 数据库（已忽略，不提交）
```

## 规范与文档

| 位置 | 内容 |
|---|---|
| [specs/proposal.md](specs/proposal.md) | 需求与范围（做什么 / 不做什么 / 可度量目标） |
| [specs/design.md](specs/design.md) | 系统架构、数据模型、接口契约、ADR |
| [specs/tasks.md](specs/tasks.md) | 任务分解与验收标准 |
| `docs/` | 需求分析、用例图、变更审核、code-review、一致性检查、规范审计、回归测试、总结报告、AI 使用声明等过程文档 |
| `docs/uml/` | PlantUML 源文件与导出图：用例图、业务流程图、四层架构图、领域模型/端口/异常类图、3 张序列图、ER 图等 14 份 |
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
