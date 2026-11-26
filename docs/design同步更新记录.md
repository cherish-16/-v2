# design.md 同步更新记录

| 项目 | 内容 |
|---|---|
| 阶段 | 阶段二 · 第 4 周 |
| 记录角色 | 架构师 |
| 触发变更 | 变更单 CR-2026-11-25-01（新增飞书考勤采集，对应教材第 7.5 节 v1.1 场景） |
| 同步顺序 | proposal → design → tasks → 代码 → 回归（规范先行） |
| 记录日期 | 2026-11-25（初版） / 2026-11-26（本次修正与复核） |

> 原则：`design.md` 的任何改动都必须有对应的 `proposal.md` 范围条目与 `tasks.md` 任务；
> 代码与设计不一致时，要么改代码，要么走规范变更，不允许悄悄不一致。

## 1. 同步范围总览

| 规范文件 | 同步内容 | 提交 |
|---|---|---|
| `specs/proposal.md` | 新增 R-11（采集考勤并纳入日报）、AC-10；N-03 由“不做”标记为已纳入 | `4cfd33c` |
| `specs/design.md` | 新增 §3.6 考勤接口契约与数据模型、ADR-005、§6 变更预留说明；`SourceBundle` 增加可选字段 | `4cfd33c` |
| `specs/tasks.md` | 新增 T4-01~T4-05；T3-10/T3-11 标记为受影响任务 | `4cfd33c` |

## 2. design.md 具体更新点

| 章节 | 更新内容 | 与代码的对应 |
|---|---|---|
| §3.6 考勤采集（新增） | 定义 `AttendanceSource` Protocol：`collect_attendance(since, until) -> list[AttendanceRecord]` | `collectors/feishu.py`、`collectors/base.py` |
| §3.6 数据模型 | 新增 `AttendanceRecord`（record_id、member_open_id、work_date、status、checked_in_at、checked_out_at） | `models.py` |
| §3.6 向后兼容 | `SourceBundle.attendance_source` 为可选字段，未配置时行为不变 | `collectors/base.py` |
| §3.6 生成层 | `generate_report(..., attendance=())` 新增关键字参数，默认空 | `generation/builder.py` |
| §3.6 条目语义 | `source_type="feishu_attendance"`，按 status 渲染出勤/缺勤/迟到/请假 | `generation/attribution.py`、`builder.py` |
| §4 ADR-005（新增） | 考勤以独立 Protocol 接入；否决“改 `collect_tasks` 签名”与“生成层直读库” | `collectors/base.py` |
| §6 变更预留 | 原第 3 周预留的考勤方案在本次变更中正式落地 | 同上 |

## 3. 本次修正（2026-11-26）

复核时发现一处规范与实现不一致：

| 项 | 修正前（design.md §3.6） | 修正后 | 原因 |
|---|---|---|---|
| 条目插入位置 | “由 `Settings.attendance_position` 决定（`after_commits` / `end`，默认 `end`）” | “考勤条目统一追加在个人日报条目末尾；`Settings.attendance_position` 暂保留未使用，若启用须先走规范变更” | 代码仅在 `config.py` 声明该字段，生成层从未读取；规范描述的行为并不存在 |

对应调整：

- `docs/规范审计报告.md` 发现 A-01 由“待处理”改为“已关闭”；
- 未删改 `config.py` 中的字段（避免超出本次文档同步范围），但在规范中明确标注未启用。

## 4. 代码层同步（供对照，不属于本文档改动）

| 提交 | 内容 |
|---|---|
| `d3e3bca` | T4-03 考勤采集（规范变更后实现） |
| `3bbdb32` | T4-04 日报生成容纳考勤条目，既有行为不回归 |
| `c0c3287` | T4-05 从成功标准导出的全量回归 |
| `e0a09ed` | 复审缺陷修复（含考勤路径） |

## 5. 验证结果（2026-11-26）

| 检查项 | 命令 | 结果 |
|---|---|---|
| 全量测试 | `uv run pytest -q` | 124 passed |
| 静态扫描 | `uv run ruff check src tests` | All checks passed |
| 分支级规范漂移 | `uv run python scripts/check_spec_drift.py --base origin/main` | 通过（代码 28 / 规范文档 4，退出码 0） |
| 单提交漂移 | `uv run python scripts/check_spec_drift.py --base HEAD~1` | 报警（预期，规范先行顺序所致） |

## 6. 结论

- `design.md` 已与 `proposal.md`、`tasks.md` 及 v2 代码在考勤变更上保持一致。
- 唯一历史漂移（`attendance_position`）已通过修改规范消除，并登记在审计报告。
- 后续若启用该配置项，须先提交规范变更与任务，再改代码。

| 角色 | 姓名 | 日期 |
|---|---|---|
| 架构师（同步与复核） |  | 2026-11-26 |
| 配置管理员（版本入库确认） |  |  |
