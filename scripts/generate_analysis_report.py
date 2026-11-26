"""生成《系统分析报告》Word 文档（docs/系统分析报告.docx）。

用法：
    uv run --with python-docx python scripts/generate_analysis_report.py

内容基于 specs/design.md、docs/需求分析报告.md 与 src/daily_report 实际代码，
图表以等宽 ASCII 呈现，中文按双宽计算对齐，保证 Word 中不错位。
"""

from __future__ import annotations

import unicodedata

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = "docs/系统分析报告.docx"

# ---------------------------------------------------------------- 等宽对齐工具


def vlen(text: str) -> int:
    """视觉宽度：CJK 全角字符按 2 列计。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def vpad(text: str, width: int) -> str:
    return text + " " * (width - vlen(text))


def box(title: str, rows: list[str]) -> list[str]:
    """画一个内容盒，右边界自动按视觉宽度对齐。"""
    inner = max(vlen(r) for r in ([title] + rows)) + 2
    top = f"┌─ {vpad(title, inner - 4)}─┐" if title else "┌" + "─" * inner + "┐"
    lines = [top]
    for r in rows:
        lines.append("│ " + vpad(r, inner - 2) + " │")
    lines.append("└" + "─" * inner + "┘")
    return lines


def hjoin(blocks: list[list[str]], gap: int = 4) -> list[str]:
    """把多个行块横向拼接，逐行按视觉宽度补齐。"""
    widths = [max(vlen(l) for l in b) for b in blocks]
    height = max(len(b) for b in blocks)
    out = []
    for i in range(height):
        parts = []
        for b, w in zip(blocks, widths):
            line = b[i] if i < len(b) else ""
            parts.append(vpad(line, w))
        out.append((" " * gap).join(parts).rstrip())
    return out


def center(blocks: list[str], width: int) -> list[str]:
    return [(" " * max(0, (width - vlen(l)) // 2)) + l for l in blocks]


# ---------------------------------------------------------------- docx 基础设施


def _set_font(run, latin: str = "Times New Roman", east_asia: str = "SimSun", size: float = 10.5, bold: bool = False) -> None:
    run.font.name = latin
    run.font.size = Pt(size)
    run.font.bold = bold
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), latin)
    rFonts.set(qn("w:hAnsi"), latin)
    rFonts.set(qn("w:eastAsia"), east_asia)
    rFonts.set(qn("w:cs"), latin)


def setup_document(doc: Document) -> None:
    for section in doc.sections:
        section.page_width = Cm(21.0)
        section.page_height = Cm(29.7)
        section.top_margin = Cm(2.5)
        section.bottom_margin = Cm(2.5)
        section.left_margin = Cm(2.6)
        section.right_margin = Cm(2.6)

    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(10.5)
    rPr = normal._element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), "Times New Roman")
    rFonts.set(qn("w:hAnsi"), "Times New Roman")
    rFonts.set(qn("w:eastAsia"), "SimSun")

    for name, size in (("Heading 1", 16), ("Heading 2", 13), ("Heading 3", 12)):
        style = doc.styles[name]
        style.font.name = "Arial"
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor(0, 0, 0)
        rPr = style._element.get_or_add_rPr()
        rFonts = rPr.get_or_add_rFonts()
        rFonts.set(qn("w:ascii"), "Arial")
        rFonts.set(qn("w:hAnsi"), "Arial")
        rFonts.set(qn("w:eastAsia"), "SimHei")


def set_cell_bg(cell, hex_color: str) -> None:
    shd = cell._tc.get_or_add_tcPr().makeelement(
        qn("w:shd"), {qn("w:val"): "clear", qn("w:fill"): hex_color}
    )
    cell._tc.get_or_add_tcPr().append(shd)


class ReportWriter:
    def __init__(self, doc: Document) -> None:
        self.doc = doc

    def h1(self, text: str) -> None:
        self.doc.add_heading(text, level=1)

    def h2(self, text: str) -> None:
        self.doc.add_heading(text, level=2)

    def h3(self, text: str) -> None:
        self.doc.add_heading(text, level=3)

    def p(self, text: str, bold: bool = False) -> None:
        para = self.doc.add_paragraph()
        run = para.add_run(text)
        run.bold = bold
        return para

    def bullets(self, items: list[str]) -> None:
        for item in items:
            self.doc.add_paragraph(item, style="List Bullet")

    def numbered(self, items: list[str]) -> None:
        for item in items:
            self.doc.add_paragraph(item, style="List Number")

    def code(self, lines: list[str]) -> None:
        """等宽代码块：单段落 + 软换行 + 浅灰底纹。"""
        para = self.doc.add_paragraph()
        para.paragraph_format.space_before = Pt(4)
        para.paragraph_format.space_after = Pt(4)
        para.paragraph_format.left_indent = Cm(0.3)
        pPr = para._p.get_or_add_pPr()
        shd = pPr.makeelement(
            qn("w:shd"), {qn("w:val"): "clear", qn("w:fill"): "F2F2F2"}
        )
        pPr.append(shd)
        for i, line in enumerate(lines):
            run = para.add_run(line)
            _set_font(run, latin="Consolas", east_asia="SimSun", size=8.5, bold=False)
            if i < len(lines) - 1:
                run.add_break(WD_BREAK.LINE)

    def table(self, headers: list[str], rows: list[list[str]], font_size: float = 9.5):
        table = self.doc.add_table(rows=1, cols=len(headers))
        table.style = "Table Grid"
        hdr = table.rows[0].cells
        for i, text in enumerate(headers):
            hdr[i].text = ""
            run = hdr[i].paragraphs[0].add_run(text)
            _set_font(run, latin="Arial", east_asia="SimHei", size=font_size, bold=True)
            set_cell_bg(hdr[i], "D9E2F3")
        for row in rows:
            cells = table.add_row().cells
            for i, text in enumerate(row):
                cells[i].text = ""
                run = cells[i].paragraphs[0].add_run(str(text))
                _set_font(run, latin="Times New Roman", east_asia="SimSun", size=font_size, bold=False)
        self.doc.add_paragraph()
        return table

    def page_break(self) -> None:
        self.doc.add_page_break()


# ---------------------------------------------------------------- 封面与目录


def cover(doc: Document) -> None:
    for _ in range(5):
        doc.add_paragraph()
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("系统分析报告")
    _set_font(run, latin="Arial", east_asia="SimHei", size=28, bold=True)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub.add_run("智能日报生成器（daily-report v2.0）")
    _set_font(run, latin="Arial", east_asia="SimSun", size=15, bold=False)

    for _ in range(4):
        doc.add_paragraph()

    info = doc.add_table(rows=5, cols=2)
    info.alignment = 1
    info.style = "Table Grid"
    rows = [
        ("文档名称", "系统分析报告"),
        ("项目名称", "智能日报生成器 daily-report v2.0"),
        ("代码基线", "feature 分支（specs/design.md v2.0，含 v1.1 考勤变更）"),
        ("编写日期", "2026 年 11 月 26 日"),
        ("参考文档", "specs/proposal.md · specs/design.md · docs/需求分析报告.md"),
    ]
    for i, (k, v) in enumerate(rows):
        c0, c1 = info.rows[i].cells
        c0.text, c1.text = "", ""
        run = c0.paragraphs[0].add_run(k)
        _set_font(run, latin="Arial", east_asia="SimHei", size=11, bold=True)
        set_cell_bg(c0, "EDF2F9")
        run = c1.paragraphs[0].add_run(v)
        _set_font(run, latin="Times New Roman", east_asia="SimSun", size=11, bold=False)
    for row in info.rows:
        row.cells[0].width = Cm(4.0)
        row.cells[1].width = Cm(11.0)

    doc.add_page_break()


def toc(doc: Document) -> None:
    doc.add_heading("目  录", level=1)
    para = doc.add_paragraph()
    run = para.add_run()
    fld_begin = run._element.makeelement(
        qn("w:fldChar"), {qn("w:fldCharType"): "begin"}
    )
    instr = run._element.makeelement(qn("w:instrText"), {})
    instr.set(qn("xml:space"), "preserve")
    instr.text = r'TOC \o "1-2" \h \z \u'
    fld_sep = run._element.makeelement(
        qn("w:fldChar"), {qn("w:fldCharType"): "separate"}
    )
    hint = run._element.makeelement(qn("w:t"), {})
    hint.text = "（在 Word 中全选后按 F9，或右键此处选择“更新域”以生成目录）"
    fld_end = run._element.makeelement(qn("w:fldChar"), {qn("w:fldCharType"): "end"})
    for el in (fld_begin, instr, fld_sep, hint, fld_end):
        run._element.append(el)
    doc.add_page_break()


# ---------------------------------------------------------------- 第 1 章


def chapter1(w: ReportWriter) -> None:
    w.h1("第1章 分析概述与技术目标")

    w.h2("1.1 项目背景与定位")
    w.p(
        "本项目为软件工程职业技能实践课程设计“智能日报生成器”的第二个迭代（v2.0）。"
        "系统面向小型研发团队，解决三个手工日报痛点：信息散落在 GitHub 与飞书两个平台、"
        "成员口头汇报易漏项、负责人汇总耗时且口径不一。"
    )
    w.p(
        "系统每个工作日定时触发一次：从 GitHub 拉取当日提交、从飞书拉取任务与群消息"
        "（v1.1 起可选接入飞书考勤），按成员归组生成每人一份个人日报与一份团队日报，"
        "经邮件与飞书群机器人两个渠道推送，并把全部原始记录、日报与运行摘要落库 SQLite，"
        "支持历史查询与重复触发防护。"
    )

    w.h2("1.2 技术目标")
    w.p("结合 proposal 的范围条目与 design.md 的非功能需求，本迭代确立六项可验证的技术目标：")
    w.table(
        ["编号", "技术目标", "含义与判定口径"],
        [
            ["T-1", "时间正确性", "全部时间统一归一为 UTC aware 存储，展示按团队时区转换；"
             "“团队时区的一天”换算为 UTC 半开区间 [start, end)，杜绝跨时区重复或漏采"],
            ["T-2", "幂等性", "同一团队同一天只允许一次有产出（success/partial）的运行；"
             "重复触发返回 skipped，不产生重复日报与重复邮件，--force 可显式重跑"],
            ["T-3", "失败隔离", "任一采集源、任一成员日报、任一推送渠道失败均不中断整体流程，"
             "失败项记入 RunSummary.failed 并反映在状态判定中"],
            ["T-4", "可追溯性", "每条日报条目必须携带非空 source_type + source_id，"
             "可回溯到原始提交 / 任务 / 消息 / 考勤记录"],
            ["T-5", "可维护性", "四层架构 + 端口适配器；依赖方向由 tests/test_architecture.py 自动守护"],
            ["T-6", "安全合规", "密钥只经 config.py 读取且 repr 脱敏；SQL 全部参数化；"
             "日志与失败原因中的邮箱一律脱敏"],
        ],
    )

    w.h2("1.3 技术选型与运行环境")
    w.table(
        ["类别", "选型", "理由"],
        [
            ["语言", "Python ≥ 3.12", "StrEnum / datetime.UTC 等新特性简化枚举与时区处理"],
            ["HTTP", "httpx ≥ 0.27", "同步 Client 满足定时批处理；超时与重试统一收口于 net.py"],
            ["存储", "SQLite（标准库 sqlite3）", "单机零运维；部分唯一索引直接表达幂等约束"],
            ["时区", "标准库 zoneinfo + tzdata", "Windows 亦可用，无第三方依赖"],
            ["命令行", "argparse（标准库）", "子命令简单，无需引入 click"],
            ["邮件", "smtplib（标准库）", "SMTP_SSL 足够，避免额外依赖"],
            ["测试", "pytest ≥ 8 + pytest-cov", "单元 / 集成 / 架构守护 / 回归四层测试"],
            ["静态检查", "ruff（E/F/I/UP/B 规则集）", "统一风格，行宽 100"],
        ],
    )

    w.h2("1.4 分析方法与报告范围")
    w.p(
        "本报告以 specs/proposal.md（范围与成功标准）、specs/design.md（架构与数据模型）"
        "为基准，对照 src/daily_report 实际代码逐模块核对后编写，图示与代码保持一致。"
        "后续章节依次给出：四层架构与模块划分（第 2 章）、对象与类建模含类图和关键序列图"
        "（第 3 章）、数据结构设计含 ER 图与 SQLite 表结构（第 4 章）、各模块函数级接口契约"
        "（第 5 章）、由验收标准导出的测试方案（第 6 章）。"
    )
    w.page_break()


# ---------------------------------------------------------------- 第 2 章


def chapter2(w: ReportWriter) -> None:
    w.h1("第2章 系统架构与模块划分（四层结构）")

    w.h2("2.1 四层总体结构")
    w.p(
        "系统采用“分层 + 端口适配器（轻量）”架构风格，划分为四个业务层："
        "主编排入口层、采集层、生成层（含渲染）、推送层；"
        "另有共享基础层（models、errors、config、net、storage）被所有层依赖。总体结构如下："
    )
    arch = box(
        "主编排入口层  orchestration/run_daily.py · cli.py",
        [
            "幂等检查 → 采集 → 生成 → 渲染 → 推送 → 写运行摘要",
            "（唯一允许同时依赖采集、生成、推送三层的模块）",
        ],
    )
    collect = box("采集层 collectors/", [
        "github    GitHubCommitSource",
        "feishu    FeishuTask/Message/AttendanceSource",
        "mock      MockSourceBundle（离线演示）",
        "base      四个采集端口 Protocol",
    ])
    gen = box("生成层 generation/ · render/", [
        "attribution  记录 → 成员归组（纯函数）",
        "builder      归组 → DailyReport",
        "text         DailyReport → 纯文本 / HTML",
    ])
    pub = box("推送层 publishers/", [
        "email       SmtpEmailPublisher",
        "feishu_bot  WebhookBotPublisher",
        "fake        FakePublisher（测试）",
        "base        渠道端口 Protocol",
    ])
    base = box("共享基础层", [
        "models   领域数据结构（无 IO）",
        "errors   异常体系",
        "config   配置装配（密钥唯一读取点）",
        "net      HTTP 超时与重试（ADR-003）",
        "storage  schema DDL + Repository",
    ])
    gap = " " * 6
    width = max(vlen(l) for l in hjoin([collect, gen, pub]))
    arrows1 = center(["└──────────┬─────────┘   └──────────┬──────────┘   └──────────┬─────────┘"], width)
    arrows2 = center(["┌───────────▼────────────────────────▼─────────────────────────▼────────┐"], width)
    body = hjoin([base], gap=0)
    middle = hjoin([collect, gen, pub])
    diagram = (
        arch
        + ["   │", "   ├──► 采集 / 生成 / 推送 三层并行调度"]
        + middle
        + arrows1
        + arrows2
        + center(body, width)
    )
    w.code(diagram)

    w.h2("2.2 各层职责与依赖规则")
    w.table(
        ["层", "职责", "允许依赖"],
        [
            ["主编排入口层", "串联全流程、幂等控制、失败隔离、汇总 RunSummary；"
             "cli.py 负责参数解析与退出码", "采集层 + 生成层 + 推送层 + 共享基础层"],
            ["采集层", "对接 GitHub REST 与飞书开放平台，产出领域记录；"
             "mock 实现与真实实现同契约", "共享基础层"],
            ["生成层", "纯函数归组与日报构建；渲染层只管呈现不做数据加工", "共享基础层"],
            ["推送层", "把渲染结果投递到邮件 / 飞书渠道，返回结构化结果；不生成内容", "共享基础层"],
            ["共享基础层", "领域模型、异常、配置、网络与持久化等横切能力", "仅标准库与 httpx"],
        ],
    )
    w.p(
        "依赖方向约束：采集层、生成层、推送层只依赖共享基础层；只有 orchestration/ 可以同时"
        "依赖三者。任何下层模块反向 import 上层视为分层违规，由 tests/test_architecture.py "
        "在每次测试时自动检查。",
        bold=True,
    )

    w.h2("2.3 模块清单与职责边界")
    w.table(
        ["模块", "职责边界（一句话）"],
        [
            ["config.py", "从环境变量与 .env 装配全部配置；是密钥的唯一读取点，不读其他文件、不访问网络"],
            ["models.py", "全部领域数据结构；构造时归一 UTC，无业务逻辑、无 IO"],
            ["errors.py", "异常类型体系；不含处理策略"],
            ["net.py", "HTTP 调用统一 10s 超时与按异常类型分流的重试（ADR-003）"],
            ["members.py", "成员 JSON 文件的加载与校验"],
            ["storage/schema.py", "建表 DDL（全部 IF NOT EXISTS 幂等）与 init_db"],
            ["storage/repository.py", "原始记录与日报的持久化、查询；全项目唯一写 SQL 的模块"],
            ["collectors/base.py", "四个采集端口 Protocol 与 SourceBundle 定义"],
            ["collectors/github.py", "GitHub REST 提交采集（分页 + 分支过滤）；只产出 CommitRecord"],
            ["collectors/feishu.py", "飞书任务 / 消息 / 考勤采集（tenant_token 缓存）；只产出对应记录"],
            ["collectors/mock.py", "离线演示数据源；与真实实现同契约，窗口过滤语义一致"],
            ["generation/attribution.py", "原始记录 → 成员归组；映射缺失不猜测，纯函数无 IO"],
            ["generation/builder.py", "归组结果 → DailyReport（个人 / 团队）；条目可追溯约束在此强制"],
            ["render/text.py", "DailyReport → 纯文本 / 邮件 HTML / 团队分组文本；纯函数"],
            ["publishers/base.py", "EmailPublisher / BotPublisher 端口与 SendResult / PushResult"],
            ["publishers/email.py", "SMTP_SSL 推送；单收件人失败隔离、认证失败整批停止、邮箱脱敏"],
            ["publishers/feishu_bot.py", "群机器人 webhook 推送"],
            ["publishers/fake.py", "可注入失败的测试替身"],
            ["orchestration/run_daily.py", "编排入口：幂等、隔离、状态判定、运行摘要落库"],
            ["cli.py", "members import/list 与 run 两个子命令；退出码 0/1/2"],
        ],
    )

    w.h2("2.4 关键架构决策（ADR 摘要）")
    w.table(
        ["编号", "决策", "理由与效果"],
        [
            ["ADR-003", "HTTP 按异常类型分流重试：401/403 直接抛 AuthenticationError 不重试；"
             "429/5xx 指数退避重试；其它 4xx 抛 TransientError 不重试",
             "认证失败重试只会放大无效请求；同请求重发不会有不同结果"],
            ["ADR-005", "考勤作为第四类数据源，新增独立 AttendanceSource 端口，"
             "SourceBundle 中以可选字段注入",
             "不修改既有 collect_tasks 语义（单一职责）；未配置考勤时行为与 v2.0 完全一致，"
             "实现只改一个装配点"],
            ["幂等约束", "run_summaries 上建部分唯一索引 (team_id, run_date) WHERE status IN "
             "('success','partial')",
             "success 与 partial 都已产生推送，必须唯一以防重触发二次发信；"
             "failed 不受限，全渠道失败后允许当日重试"],
            ["降级保护", "daily_reports 的 upsert 带 WHERE：新报告条目数不少于已存报告才允许覆盖",
             "采集源临时失败时重新生成，不会把好日报冲成“无数据”"],
            ["配置收口", "config.py 是密钥唯一读取点；敏感字段 repr=False",
             "日志与 traceback 不泄露令牌；测试显式传 env 可完全隔离 .env"],
        ],
    )
    w.page_break()


# ---------------------------------------------------------------- 第 3 章


def chapter3(w: ReportWriter) -> None:
    w.h1("第3章 对象与类建模（类图、关键序列图）")

    w.h2("3.1 领域模型类图")
    w.p("领域模型全部位于 models.py，除 DailyReport / RunSummary 外均为 frozen dataclass，无 IO：")
    member = box("Member（frozen）", [
        "member_id : str",
        "name : str",
        "github_login : str | None",
        "feishu_open_id : str | None",
        "email : str | None",
        "git_emails : tuple[str, ...]",
    ])
    commit = box("CommitRecord（frozen）", [
        "sha, author_login, message",
        "committed_at : datetime(UTC)",
        "repo, author_email",
    ])
    task = box("TaskRecord（frozen）", [
        "task_id, title, status",
        "assignee_open_id : str | None",
        "updated_at : datetime(UTC)",
    ])
    msg = box("MessageRecord（frozen）", [
        "msg_id, content, chat_id",
        "sender_open_id : str | None",
        "created_at : datetime(UTC)",
        "is_recalled : bool = False",
    ])
    att = box("AttendanceRecord（frozen）", [
        "record_id, work_date : date",
        "member_open_id : str | None",
        "status ∈ present/absent/late/leave",
        "checked_in_at / checked_out_at : UTC | None",
    ])
    item = box("ReportItem（frozen）", [
        "source_type : str",
        "source_id : str（非空，可追溯）",
        "text : str",
        "occurred_at : datetime(UTC)",
    ])
    report = box("DailyReport", [
        "scope : ReportScope（必填）",
        "entity_id : str",
        "report_date : date",
        "items : list[ReportItem]",
        "generated_at : datetime(UTC)",
        "note : str | None（无数据/来源缺失）",
    ])
    summary = box("RunSummary", [
        "team_id, run_date : date",
        "status ∈ success/skipped/partial/failed",
        "collected / sent / failed : dict",
        "started_at / finished_at : UTC",
    ])
    scope = box("«enum» ReportScope", ["PERSONAL = \"personal\"", "TEAM = \"team\""])

    w.code(hjoin([member, commit, task]))
    w.code(hjoin([msg, att, scope]))
    w.code(
        hjoin([item, report, summary])
        + ["",
           "  DailyReport ◆── 1..* ReportItem        CommitRecord/TaskRecord/MessageRecord/"]
        + ["  AttendanceRecord 经 attribution 归组后折叠为 ReportItem；RunSummary 与"
           " DailyReport 1:1 于一次运行"]
    )

    w.h2("3.2 端口与适配器类图")
    w.p(
        "采集侧与推送侧各定义 Protocol 端口（collectors/base.py、publishers/base.py），"
        "真实实现、Mock 实现与测试替身共享同一契约，编排层只依赖端口："
    )
    cs = box("«protocol» CommitSource", [
        "collect_commits(owner, repo,",
        "  since, until, *, max_pages)",
        "  -> list[CommitRecord]",
    ])
    ts = box("«protocol» TaskSource", [
        "collect_tasks(since, until)",
        "  -> list[TaskRecord]",
    ])
    ms = box("«protocol» MessageSource", [
        "collect_messages(since, until)",
        "  -> list[MessageRecord]",
    ])
    as_ = box("«protocol» AttendanceSource", [
        "collect_attendance(since, until)",
        "  -> list[AttendanceRecord]",
    ])
    sb = box("SourceBundle", [
        "commit_source / task_source",
        "message_source",
        "attendance_source = None（可选）",
    ])
    gh = box("GitHubCommitSource", ["分页拉取 + 分支过滤"])
    fs = box("Feishu 三源实现", ["_FeishuBase: token 缓存"])
    mk = box("Mock 三源实现", ["窗口过滤 + 注入数据"])
    ep = box("«protocol» EmailPublisher", ["send_email(report, recipients)", "-> SendResult"])
    bp = box("«protocol» BotPublisher", ["push_to_feishu(report)", "-> PushResult"])
    smtp = box("SmtpEmailPublisher", ["SMTP_SSL，失败隔离"])
    bot = box("WebhookBotPublisher", ["webhook POST"])
    fake = box("FakePublisher", ["可注入失败"])

    left = hjoin([cs, ts]) + ["     ▲ implements        ▲ implements"] + hjoin([gh, mk])
    right = hjoin([ms]) + ["     ▲ implements"] + hjoin([fs]) + [""] + hjoin([as_])
    w.code(hjoin([left, sb, right]))
    w.code(
        hjoin([ep, bp])
        + ["     ▲ implements          ▲ implements"]
        + hjoin([smtp, fake, bot])
    )

    w.h2("3.3 异常体系类图")
    w.code(
        box("ReportError（code 属性）", [])
        + ["   ▲" for _ in range(1)]
        + ["   ├── ConfigError        配置缺失 / 非法（启动时暴露）",
           "   ├── AuthenticationError  401/403，不重试",
           "   ├── TransientError       超时 / 429 / 5xx 重试耗尽，或其它 4xx",
           "   └── TraceabilityError    日报条目 source_id 为空，破坏可追溯约束"]
    )
    w.p(
        "另有独立的 MemberFileError（members.py），用于成员文件校验失败；"
        "它不属于 ReportError 体系，因为成员文件在编排开始前即可独立校验。"
    )

    w.h2("3.4 关键序列图")
    w.h3("3.4.1 序列图一：run_daily 主流程（采集 → 归组生成 → 落库）")
    w.p("参与方：CLI、run_daily（编排）、采集端口、Repository（存储）、生成层。")
    seq1 = [
        "CLI          run_daily          Repository        采集端口         生成层",
        " │               │                   │                │               │",
        " ├──run_daily───►│                   │                │               │",
        " │               ├─find_latest_run──►│                │               │",
        " │               │◄──已有 success/partial 且未 force？──────────┐    │",
        " │               │   是：返回 status=skipped 的 RunSummary     │    │",
        " │               ├─_day_window(date, tz)：团队时区→UTC [start,end)",
        " │               ├─collect_commits(since,until)──────────────►│    │",
        " │               ├─collect_tasks / collect_messages ─────────►│    │",
        " │               ├─(可选)collect_attendance ─────────────────►│    │",
        " │               │   单源异常→failed[src]=类型名，继续其余源  │    │",
        " │               ├─save_commits / save_tasks / save_messages─►│    │",
        " │               ├─list_members─────────────────────────────►│    │",
        " │               ├─attribute(members, 4 类记录)────────────────────►│",
        " │               │        （映射缺失→unmapped，不猜测归属）    │     │",
        " │               ├─generate_report(PERSONAL, 每成员)────────────────►│",
        " │               ├─generate_report(TEAM, team_id)──────────────────►│",
        " │               │   单人异常→failed[personal:id]，继续其余   │      │",
        " │               ├─save_report(report)（降级保护 upsert）────►│      │",
        " │               │◄───────────个人 + 团队 DailyReport───────────────┤",
    ]
    w.code(seq1)

    w.h3("3.4.2 序列图二：推送与运行摘要（双渠道隔离）")
    seq2 = [
        "run_daily       render/text      SmtpEmailPublisher     WebhookBot      Repository",
        "   │                 │                   │                  │              │",
        "   ├─recipients=成员邮箱去重              │                  │              │",
        "   ├─send_email(team_report, rcpts)──────►│                  │              │",
        "   │                 ├──render_email_html│                  │              │",
        "   │                 ├──逐封 SMTP_SSL 发送│                  │              │",
        "   │                 │   单封失败→failed 记录（脱敏），继续│              │",
        "   │                 │   认证失败→整批停止，其余标 skipped│              │",
        "   │                 │◄─────────SendResult(success, failed)──────────────│",
        "   ├─push_to_feishu(team_report)──────────────────────────►│              │",
        "   │                 │                   │  POST webhook    │              │",
        "   │                 │◄──────────PushResult(ok, error)───────────────────│",
        "   ├─状态判定：failed 且渠道全挂→failed；有失败→partial；否则 success",
        "   ├─save_run_summary(RunSummary)──────────────────────────────────────────►│",
        "   │◄────────────────────── RunSummary（CLI 打印并决定退出码）───────────────┤",
    ]
    w.code(seq2)

    w.h3("3.4.3 序列图三：飞书采集的鉴权与重试")
    seq3 = [
        "FeishuXxxSource     _FeishuBase(缓存)        net.get_json        飞书开放平台",
        "     │                     │                      │                  │",
        "     ├─_auth_headers()────►│ token 未过期直接复用 │                  │",
        "     │                     ├─POST token（过期时）─►│─────────────────►│",
        "     ├─collect_xxx(since,until)                  │                  │",
        "     │                     ├─GET 业务接口────────►│  10s 超时         │",
        "     │                     │               401/403→AuthenticationError│",
        " │   │                     │               429/5xx→退避重试≤retry_times│",
        "     │                     │◄────────list[Record]（epoch ms→UTC）──────│",
    ]
    w.code(seq3)

    w.h2("3.5 对象不变式汇总")
    w.table(
        ["不变式", "强制位置"],
        [
            ["所有 datetime 字段必须 UTC aware，构造时归一为 UTC", "models.ensure_utc，各记录 __post_init__"],
            ["naive datetime 一律拒绝（ValueError）", "同上"],
            ["ReportItem.source_id 非空，否则 TraceabilityError", "models 与 builder._require"],
            ["AttendanceRecord.status ∈ {present, absent, late, leave}", "models.ATTENDANCE_STATUSES"],
            ["AttendanceRecord.record_id 非空（可追溯）", "models.__post_init__"],
            ["RunSummary.status ∈ {success, skipped, partial, failed}", "models.__post_init__"],
            ["DailyReport.scope 必填、无默认值", "builder.generate_report 签名"],
            ["无数据日返回带 note=\"无数据\" 的日报，绝不返回 None", "builder._compose_note"],
            ["考勤记录 checked_in/out_at 为 None 表示未打点，不是数据缺失", "models 文档契约 + builder 渲染规则"],
        ],
    )
    w.page_break()


# ---------------------------------------------------------------- 第 4 章


def chapter4(w: ReportWriter) -> None:
    w.h1("第4章 数据结构设计（ER 图、SQLite 表结构）")

    w.h2("4.1 概念模型与 ER 图")
    w.p(
        "数据库共 6 张表。members 与三类原始记录之间是“账号映射”的逻辑归属关系"
        "（github_login / feishu_open_id / git_emails 字段匹配），刻意不建外键："
        "原始记录以平台为准只追加落库，成员映射可随时补配并重新生成日报，"
        "归属运算在生成层（attribution）完成而非在库内完成。"
    )
    er = (
        box("members", [
            "member_id  PK",
            "name",
            "github_login ──┐",
            "feishu_open_id │ 逻辑映射（非外键）",
            "email          │",
            "git_emails ────┘",
        ])
        + ["      │ 1                    │ 1                        │ 1",
           "      │ 归属(github_login)   │ 归属(feishu_open_id)     │ 归属(git_emails)",
           "      ▼ N                    ▼ N                        ▼ N"]
        + hjoin([
            box("commit_records", ["sha PK", "author_login", "author_email"]),
            box("task_records", ["task_id PK", "assignee_open_id"]),
            box("message_records", ["msg_id PK", "sender_open_id"]),
        ])
        + ["",
           "┌──────────────────────────────┐   ┌─────────────────────────────────────┐",
           "│ daily_reports                │   │ run_summaries                       │",
           "│ id PK AUTOINCREMENT          │   │ id PK AUTOINCREMENT                 │",
           "│ (scope, entity_id,           │   │ (team_id, run_date) 唯一            │",
           "│  report_date) UNIQUE         │◄──┤ WHERE status IN ('success','partial')",
           "│ body_json：条目含 source_id  │业务│ idx_run_productive_unique 部分唯一  │",
           "│ note：无数据 / 来源缺失      │对应│ status ∈ 4 枚举                     │",
           "└──────────────────────────────┘   └─────────────────────────────────────┘"]
    )
    w.code(er)
    w.p(
        "说明：考勤记录（AttendanceRecord）当日采集后直接参与生成，不落库；"
        "飞书侧考勤接口为权威数据源，重复查询幂等，暂无本地持久化需求（v1.1 范围决策）。"
    )

    w.h2("4.2 SQLite 表结构")
    w.p("六张表的关键列与约束如下（时间列一律存 UTC ISO8601 字符串）：")
    w.table(
        ["表", "列", "约束与说明"],
        [
            ["members", "member_id TEXT PK；name TEXT NOT NULL；github_login / feishu_open_id / "
             "email TEXT；git_emails TEXT（JSON 数组）",
             "member_id 唯一；git_emails 序列化为 JSON 以支持多邮箱归属"],
            ["commit_records", "sha TEXT PK；author_login / message / committed_at / repo NOT NULL；"
             "author_email TEXT",
             "author_login + author_email 双线索归属；INSERT OR IGNORE 按 sha 去重"],
            ["task_records", "task_id TEXT PK；title / status / updated_at NOT NULL；"
             "assignee_open_id TEXT", "同上按 task_id 去重"],
            ["message_records", "msg_id TEXT PK；content / created_at / chat_id NOT NULL；"
             "sender_open_id TEXT；is_recalled INTEGER DEFAULT 0",
             "撤回消息保留原文并打标记，日报中显示“[已撤回]”前缀"],
            ["daily_reports", "id INTEGER PK AUTOINCREMENT；scope / entity_id / report_date / "
             "generated_at / body_json NOT NULL；note TEXT",
             "UNIQUE(scope, entity_id, report_date)；upsert 带降级保护 WHERE"],
            ["run_summaries", "id INTEGER PK AUTOINCREMENT；team_id / run_date / status / "
             "collected_json / sent_json / failed_json / started_at NOT NULL；finished_at TEXT",
             "部分唯一索引 idx_run_productive_unique 保证生产性运行唯一"],
        ],
    )

    w.h2("4.3 建表 DDL（storage/schema.py）")
    w.code(
        [
            "CREATE TABLE IF NOT EXISTS members (",
            "    member_id      TEXT PRIMARY KEY,",
            "    name           TEXT NOT NULL,",
            "    github_login   TEXT,",
            "    feishu_open_id TEXT,",
            "    email          TEXT,",
            "    git_emails     TEXT);",
            "",
            "CREATE TABLE IF NOT EXISTS commit_records (",
            "    sha          TEXT PRIMARY KEY,",
            "    author_login TEXT NOT NULL,",
            "    message      TEXT NOT NULL,",
            "    committed_at TEXT NOT NULL,",
            "    repo         TEXT NOT NULL,",
            "    author_email TEXT);",
            "",
            "CREATE TABLE IF NOT EXISTS task_records (",
            "    task_id          TEXT PRIMARY KEY,",
            "    title            TEXT NOT NULL,",
            "    status           TEXT NOT NULL,",
            "    assignee_open_id TEXT,",
            "    updated_at       TEXT NOT NULL);",
            "",
            "CREATE TABLE IF NOT EXISTS message_records (",
            "    msg_id           TEXT PRIMARY KEY,",
            "    sender_open_id   TEXT,",
            "    content          TEXT NOT NULL,",
            "    created_at       TEXT NOT NULL,",
            "    chat_id          TEXT NOT NULL,",
            "    is_recalled      INTEGER NOT NULL DEFAULT 0);",
            "",
            "CREATE TABLE IF NOT EXISTS daily_reports (",
            "    id           INTEGER PRIMARY KEY AUTOINCREMENT,",
            "    scope        TEXT NOT NULL,",
            "    entity_id    TEXT NOT NULL,",
            "    report_date  TEXT NOT NULL,",
            "    generated_at TEXT NOT NULL,",
            "    body_json    TEXT NOT NULL,",
            "    note         TEXT,",
            "    UNIQUE (scope, entity_id, report_date));",
            "",
            "CREATE TABLE IF NOT EXISTS run_summaries (",
            "    id             INTEGER PRIMARY KEY AUTOINCREMENT,",
            "    team_id        TEXT NOT NULL,",
            "    run_date       TEXT NOT NULL,",
            "    status         TEXT NOT NULL,",
            "    collected_json TEXT NOT NULL,",
            "    sent_json      TEXT NOT NULL,",
            "    failed_json    TEXT NOT NULL,",
            "    started_at     TEXT NOT NULL,",
            "    finished_at    TEXT);",
            "",
            "-- 幂等约束：同一团队同一天只允许一条「有产出」的记录",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_run_productive_unique",
            "    ON run_summaries (team_id, run_date)",
            "    WHERE status IN ('success', 'partial');",
        ]
    )

    w.h2("4.4 运行参数与完整性策略")
    w.table(
        ["策略", "实现"],
        [
            ["连接参数", "PRAGMA foreign_keys=ON；PRAGMA journal_mode=WAL（并发读不阻塞写）"],
            ["SQL 纪律", "全部语句参数化（? 占位），禁止字符串拼接（NFR-S4）；全项目仅 repository.py 写 SQL"],
            ["原始记录写入", "INSERT OR IGNORE 按主键幂等去重，只追加、不修改"],
            ["日报写入", "ON CONFLICT(scope, entity_id, report_date) DO UPDATE，"
             "且新报告条目数 ≥ 已存条目数才覆盖（降级保护）"],
            ["运行摘要写入", "先 DELETE 同键旧行再 INSERT（部分唯一索引无法被 ON CONFLICT 定位）"],
            ["序列化", "日报整体序列化为 body_json（items 含 source_type/source_id/text/occurred_at）；"
             "datetime 存 ISO8601；读取时经 fromisoformat 还原为 UTC aware"],
        ],
    )
    w.page_break()


# ---------------------------------------------------------------- 第 5 章


def chapter5(w: ReportWriter) -> None:
    w.h1("第5章 接口约定（各模块函数级契约）")
    w.p(
        "本章按模块给出函数级契约。约定记法：前置条件为调用方必须保证的条件；"
        "异常列仅列本函数主动抛出的类型；被动传播的异常由编排层统一捕获隔离。"
    )

    w.h2("5.1 配置装配 config.py")
    w.table(
        ["函数", "契约"],
        [
            ["load_settings(env=None, *, env_file=None) -> Settings",
             "前置：无。优先级 显式 env > 进程环境变量 > .env 文件（当前目录 → 项目根）；"
             "显式传 env 时不读 .env（测试隔离）。后置：返回 frozen Settings。"
             "异常：ConfigError（source_mode 非法；live 模式缺 GITHUB_TOKEN；时区名无法被 ZoneInfo 解析；"
             "整型配置不是整数）"],
            ["Settings（dataclass, frozen）",
             "字段：source_mode / timezone / github_token / feishu_app_id / feishu_app_secret / "
             "smtp_host / smtp_port(默认465) / smtp_user / smtp_password / feishu_bot_webhook / "
             "max_pages(10) / retry_times(2) / github_owner / github_repo / github_branch / "
             "insecure_tls / attendance_position；敏感字段 repr=False"],
        ],
    )

    w.h2("5.2 领域模型 models.py")
    w.table(
        ["函数", "契约"],
        [
            ["ensure_utc(value: datetime) -> datetime",
             "前置：value 为 datetime。后置：返回 UTC aware。异常：ValueError（naive 输入）"],
            ["各 frozen 记录类构造",
             "__post_init__ 归一时间并校验不变式（见 3.5 节）；违反即抛 ValueError"],
        ],
    )

    w.h2("5.3 采集端口 collectors/base.py")
    w.p("时间语义统一：since 含、until 不含（半开区间 [since, until)），且必须为 UTC aware。")
    w.table(
        ["端口", "签名", "后置"],
        [
            ["CommitSource", "collect_commits(owner, repo, since, until, *, max_pages=10) "
             "-> list[CommitRecord]", "仅返回窗口内提交；分页拉取至多 max_pages 页"],
            ["TaskSource", "collect_tasks(since, until) -> list[TaskRecord]",
             "仅返回窗口内更新（飞书 epoch ms 已转 UTC）"],
            ["MessageSource", "collect_messages(since, until) -> list[MessageRecord]",
             "含撤回消息，is_recalled 标记"],
            ["AttendanceSource", "collect_attendance(since, until) -> list[AttendanceRecord]",
             "可选端口；未配置时 SourceBundle.attendance_source=None"],
        ],
    )

    w.h2("5.4 网络层 net.py")
    w.table(
        ["函数", "契约"],
        [
            ["get_json(client, url, *, params=None, headers=None, retry_times=2, sleep=time.sleep)",
             "GET 并解析 JSON，超时 10s。异常语义见下表"],
            ["post_json(client, url, *, json_body, ...)", "同 get_json，POST 语义"],
            ["_classify(status)（内部）",
             "401/403→auth；429 或 5xx→retry；其它→fail"],
        ],
    )
    w.table(
        ["情形", "处置"],
        [
            ["HTTP 401 / 403", "立即抛 AuthenticationError，不重试"],
            ["HTTP 429 / 5xx / 超时 / 传输错误", "退避重试（1s、2s），共 retry_times+1 次尝试；"
             "耗尽后抛 TransientError"],
            ["其它 4xx", "抛 TransientError，不重试（重发不会有不同结果）"],
            ["成功（<400）", "返回 response.json()"],
        ],
    )

    w.h2("5.5 成员文件 members.py")
    w.table(
        ["函数", "契约"],
        [
            ["load_member_file(path) -> list[Member]",
             "读取 JSON 数组并逐条校验。异常：MemberFileError（条目非对象、必填字段缺失或为空）。"
             "member_id/name 必填，其余字段可选；git_emails 为字符串数组"],
        ],
    )

    w.h2("5.6 存储层 storage/")
    w.table(
        ["函数", "契约"],
        [
            ["init_db(path) -> sqlite3.Connection",
             "打开或创建库，foreign_keys=ON、journal_mode=WAL，幂等执行全部 DDL"],
            ["Repository.upsert_members(members)",
             "ON CONFLICT(member_id) DO UPDATE；git_emails 序列化为 JSON"],
            ["Repository.list_members() -> list[Member]", "按 rowid 序返回"],
            ["Repository.save_commits / save_tasks / save_messages(records) -> int",
             "INSERT OR IGNORE 按主键去重；返回实际新增行数"],
            ["Repository.save_report(report)",
             "按 (scope, entity_id, report_date) upsert；新报告条目数 < 已存条目数时拒绝覆盖（降级保护）"],
            ["Repository.get_report(scope, entity_id, report_date) -> DailyReport | None",
             "按唯一键读取，body_json 反序列化"],
            ["Repository.list_reports(since, until) -> list[DailyReport]",
             "按 report_date 升序返回闭区间内的全部日报（历史查询，AC-07）"],
            ["Repository.save_run_summary(summary)",
             "先删同键旧行再插入；触发部分唯一索引约束防生产性运行重复"],
            ["Repository.find_latest_run(team_id, run_date) -> RunSummary | None",
             "返回最近一次运行（任意状态），幂等判定依据"],
            ["Repository.find_successful_run(team_id, run_date) -> RunSummary | None",
             "仅返回 status=success 的运行"],
        ],
    )

    w.h2("5.7 生成层 generation/")
    w.table(
        ["函数", "契约"],
        [
            ["attribute(members, commits, tasks, messages, attendance=()) -> AttributionResult",
             "纯函数。规则 1：映射缺失的成员列入 unmapped，绝不按姓名猜测归属；"
             "规则 2：提交优先按 github_login 归属，缺失时按 git_emails 小写匹配，"
             "任务 / 消息 / 考勤按 feishu_open_id 归属。"
             "mapping_gaps 按渠道记录半配置成员（如只配飞书未配 GitHub）"],
            ["generate_report(scope, entity_id, report_date, *, members, commits, tasks, "
             "messages, attendance=(), missing_sources=(), now=None, tz=\"Asia/Shanghai\") "
             "-> DailyReport",
             "scope 必填无默认。后置：条目顺序固定为提交→任务→消息→考勤；"
             "source_id 非空否则 TraceabilityError；无数据日返回 note 含“无数据”的日报而非 None。"
             "PERSONAL：仅本人条目 + 本人映射缺口；TEAM：按 members 声明顺序汇总，"
             "条目文本加成员名前缀，无数据成员与未映射成员写入 note"],
        ],
    )

    w.h2("5.8 渲染层 render/text.py")
    w.p("三个函数均为纯函数：不修改入参、无 IO、不做数据加工。")
    w.table(
        ["函数", "契约"],
        [
            ["render_text(report) -> str", "标题 + 逐条“[source_type] text”+ 备注"],
            ["render_email_html(report) -> str", "邮件 HTML；所有插值经 html.escape"],
            ["render_team_text(report) -> str",
             "按条目文本中第一个全角冒号前的成员名分组；切不出成员名的归入“其他”"],
        ],
    )

    w.h2("5.9 推送层 publishers/")
    w.table(
        ["接口 / 类", "契约"],
        [
            ["EmailPublisher.send_email(report, recipients) -> SendResult",
             "SendResult.success: list[str]；failed: list[(address, reason)]；ok 属性=有成功送达"],
            ["BotPublisher.push_to_feishu(report, webhook=None) -> PushResult",
             "PushResult.ok: bool；error: str | None"],
            ["SmtpEmailPublisher.send_email",
             "前置：smtp_host/user/password 齐备，否则 ConfigError。"
             "单收件人失败仅记录并继续；SMTPAuthenticationError 时整批停止、"
             "其余收件人标记 “skipped: authentication failed”；"
             "失败原因只记异常类型名（不转发可能含地址的异常文本，脱敏）"],
            ["WebhookBotPublisher.push_to_feishu",
             "经 net.post_json 发送 webhook；网络异常向上传播，由编排层隔离"],
            ["FakePublisher(fail_email=False, fail_bot=False)", "测试替身，可注入渠道失败"],
        ],
    )

    w.h2("5.10 编排入口 orchestration/run_daily.py")
    w.table(
        ["函数", "契约"],
        [
            ["run_daily(team_id, report_date, *, settings, repo, sources, publishers, "
             "now=None, force=False) -> RunSummary",
             "幂等：存在 success/partial 且未 force → 返回 skipped 摘要。"
             "采集窗口：团队时区当日 00:00–24:00 换算为 UTC 半开区间。"
             "隔离：逐源、逐成员、逐渠道 try/except。状态判定见下表。"
             "后置：RunSummary 必然落库"],
            ["_day_window(report_date, tz_name)（内部）",
             "返回 (start, end) UTC；时区名非法时告警并退回 UTC"],
        ],
    )
    w.table(
        ["status", "判定条件"],
        [
            ["skipped", "当日已有 success/partial 运行且未指定 force"],
            ["failed", "无成员配置（无产出，允许配置修正后重试）；或有推送渠道但邮件与飞书全部失败"],
            ["partial", "存在任一 failed 项，但仍有渠道成功（或未配置任何渠道）"],
            ["success", "全部采集、生成与已配置渠道均成功"],
        ],
    )

    w.h2("5.11 命令行 cli.py")
    w.table(
        ["子命令", "参数", "行为"],
        [
            ["members import", "--file（必填）、--db", "从 members.json 导入成员，打印导入数量"],
            ["members list", "--db", "列出成员及缺失的映射字段"],
            ["run", "--team（必填）、--date、--print、--force、--demo、--db",
             "执行 run_daily 并打印 JSON 摘要；--date 缺省取团队时区“今天”；"
             "--demo 使用内置三人演示数据，无需外部凭证；--print 渲染团队日报到终端"],
        ],
    )
    w.table(
        ["退出码", "含义"],
        [
            ["0", "success / partial / skipped（含重复触发）"],
            ["1", "运行失败（failed）、ReportError、成员文件错误、未配置成员"],
            ["2", "命令行参数错误"],
        ],
    )
    w.page_break()


# ---------------------------------------------------------------- 第 6 章


def chapter6(w: ReportWriter) -> None:
    w.h1("第6章 测试方案（从验收标准导出）")

    w.h2("6.1 导出方法与测试分层")
    w.p(
        "测试方案严格从《需求分析报告》第 6 章的 9 条验收标准（AC-01 ~ AC-09）导出："
        "每条验收标准映射到至少一个测试目标，每个测试目标落到具体测试文件与用例，"
        "通过标准与验收标准逐字对应。整体分四层："
    )
    w.table(
        ["层次", "内容", "实现"],
        [
            ["单元测试", "各模块函数级行为与异常语义", "tests/test_models、test_config、test_net、"
             "test_attribution、test_builder_*、test_render、test_storage、test_email_* 等"],
            ["集成测试", "mock 源 + FakePublisher 端到端跑通 run_daily", "tests/test_integration.py"],
            ["架构守护测试", "分层依赖方向、端口契约（runtime_checkable）", "tests/test_architecture.py、"
             "test_collectors_base.py"],
            ["回归测试", "修复过的缺陷固定为用例，防复发", "tests/test_regression.py、"
             "test_review_fixes.py"],
        ],
    )

    w.h2("6.2 验收标准 → 测试映射表")
    w.table(
        ["验收标准", "测试目标", "测试文件", "通过标准"],
        [
            ["AC-01 三源采集可用", "GitHub / 飞书任务 / 飞书消息采集正确、窗口过滤正确",
             "test_github_collector、test_feishu_collector、test_collectors_base",
             "mock 与真实实现同契约；窗口外数据不返回"],
            ["AC-02 个人日报生成", "归组正确、条目可追溯、无数据有标注",
             "test_builder_personal、test_attribution、test_models",
             "source_id 100% 非空；无数据日 note 含“无数据”；映射缺失不猜测"],
            ["AC-03 团队日报生成", "按成员分组、格式统一、缺失成员显式标注",
             "test_builder_team、test_render", "无数据成员与未映射成员写入 note；渲染分组正确"],
            ["AC-04 邮件推送", "逐封送达、失败隔离、认证失败整批停止",
             "test_email_pusher、test_email_matching",
             "单收件人失败不影响其余；失败原因脱敏"],
            ["AC-05 飞书推送", "webhook 推送成功且格式正确",
             "test_feishu_bot", "PushResult.ok 语义正确"],
            ["AC-06 定时与幂等", "同日二次触发被忽略；--force 可重跑",
             "test_run_daily、test_cli、test_storage",
             "第二次返回 skipped；无重复日报与重复邮件"],
            ["AC-07 历史查询", "list_reports 区间过滤正确、响应达标",
             "test_storage", "闭区间过滤正确；SQLite 本地查询 ≤ 1 秒"],
            ["AC-08 安全合规", "无硬编码令牌；日志无敏感信息",
             "test_email_pusher（mask_email）+ docs/安全自检记录.md 全仓检索",
             "密钥仅 config.py 读取；日志与失败原因脱敏"],
            ["AC-09 规范一致性", "接口 / 数据模型与 specs 无漂移",
             "scripts/check_spec_drift.py + test_architecture",
             "与《设计与 specs 一致性检查记录》一致"],
        ],
    )

    w.h2("6.3 关键测试场景设计")
    w.table(
        ["场景", "构造方式", "断言要点"],
        [
            ["幂等与重跑", "同一 (team, date) 连续调用 run_daily；再以 force=True 调用",
             "第二次 status=skipped；force 后允许重新生成推送"],
            ["失败隔离矩阵", "单源抛异常 / 单成员数据异常 / FakePublisher(fail_email, fail_bot) 组合",
             "failed 字典逐项记录类型名；整体状态按 5.10 判定表落位"],
            ["时区日窗口", "跨 UTC 日期边界的时间戳（如北京时间次日 0:30）",
             "_day_window 换算后 [since, until) 恰好覆盖团队时区全天"],
            ["归属不猜测", "成员仅配飞书未配 GitHub（及反向）",
             "mapping_gaps 按渠道记录；note 写“未配置映射成员”，绝不按姓名匹配"],
            ["降级保护", "先生成含条目日报，再以空数据重新生成",
             "条目更少的新报告不得覆盖已存报告"],
            ["考勤语义（v1.1）", "present / late / absent / leave / 未打点组合",
             "缺勤与请假不显示时刻；迟到显示打点时间；AttendanceSource 未配置时行为与变更前一致"],
            ["脱敏", "构造含 “@” 的收件地址与失败原因",
             "mask_email 输出 z***@domain；失败原因只含异常类型名"],
        ],
    )

    w.h2("6.4 测试执行结果")
    w.p("最近一次全量执行（2026-11-26，feature 分支工作区）：")
    w.table(
        ["指标", "数值"],
        [
            ["测试文件", "23 个（+conftest）"],
            ["收集用例", "130 个"],
            ["通过", "129 个"],
            ["失败", "1 个：tests/test_storage.py::test_duplicate_successful_run_rejected"],
        ],
    )
    w.p(
        "失败原因说明：该用例基于旧语义编写（重复保存生产性运行摘要时抛 IntegrityError）。"
        "当前工作区为支持 --force 重跑，save_run_summary 已改为“先删同键旧行再插入”，"
        "不再触发唯一索引异常，幂等防护上移至 run_daily 的 find_latest_run 检查。"
        "处理项：更新该用例断言为新语义（save_run_summary 幂等覆盖 + run_daily 层 skipped 判定），"
        "并同步修订 specs/design.md §2.2 的约束描述。此项已列入收尾任务，其余验收路径全部通过。"
    )

    w.h2("6.5 准出标准")
    w.bullets([
        "全部 130 个用例通过，pytest-cov 覆盖核心模块（生成层与编排层为必测重点）。",
        "test_architecture 分层守护通过：基础层不得 import 上层模块。",
        "ruff（E/F/I/UP/B，行宽 100）零告警。",
        "AC-01 ~ AC-09 的映射用例全部绿色，且 specs/ 文档与代码一致性检查通过。",
    ])


def main() -> None:
    doc = Document()
    setup_document(doc)
    w = ReportWriter(doc)
    cover(doc)
    toc(doc)
    chapter1(w)
    chapter2(w)
    chapter3(w)
    chapter4(w)
    chapter5(w)
    chapter6(w)
    doc.save(OUT)
    print(f"已生成 {OUT}")


if __name__ == "__main__":
    main()
