"""仓储层：全部 SQL 的唯一所在地。

纪律：所有语句参数化（``?`` 占位），禁止字符串拼接 —— 见 design.md NFR-S4。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import date, datetime

from daily_report.models import (
    CommitRecord,
    DailyReport,
    Member,
    MessageRecord,
    ReportItem,
    ReportScope,
    RunSummary,
    TaskRecord,
)

_ISO = "%Y-%m-%dT%H:%M:%S%z"


def _to_text(value: datetime) -> str:
    return value.isoformat()


def _from_text(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {value!r}")


class Repository:
    """原始记录与日报的持久化。

    原始记录只追加（``INSERT OR IGNORE`` 按主键去重）；日报按键 upsert。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ---------- 成员 ----------

    def upsert_members(self, members: Sequence[Member]) -> None:
        self._conn.executemany(
            """
            INSERT INTO members
                (member_id, name, github_login, feishu_open_id, email, git_emails)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(member_id) DO UPDATE SET
                name=excluded.name,
                github_login=excluded.github_login,
                feishu_open_id=excluded.feishu_open_id,
                email=excluded.email,
                git_emails=excluded.git_emails
            """,
            [
                (
                    m.member_id,
                    m.name,
                    m.github_login,
                    m.feishu_open_id,
                    m.email,
                    json.dumps(list(m.git_emails), ensure_ascii=False),
                )
                for m in members
            ],
        )
        self._conn.commit()

    def list_members(self) -> list[Member]:
        rows = self._conn.execute(
            "SELECT member_id, name, github_login, feishu_open_id, email, git_emails "
            "FROM members ORDER BY rowid"
        ).fetchall()
        return [
            Member(
                member_id=row[0],
                name=row[1],
                github_login=row[2],
                feishu_open_id=row[3],
                email=row[4],
                git_emails=tuple(json.loads(row[5])) if row[5] else (),
            )
            for row in rows
        ]

    # ---------- 原始记录 ----------

    def save_commits(self, records: Sequence[CommitRecord]) -> int:
        cur = self._conn.executemany(
            """
            INSERT OR IGNORE INTO commit_records
                (sha, author_login, message, committed_at, repo, author_email)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r.sha,
                    r.author_login,
                    r.message,
                    _to_text(r.committed_at),
                    r.repo,
                    r.author_email,
                )
                for r in records
            ],
        )
        self._conn.commit()
        return cur.rowcount

    def save_tasks(self, records: Sequence[TaskRecord]) -> int:
        cur = self._conn.executemany(
            """
            INSERT OR IGNORE INTO task_records
                (task_id, title, status, assignee_open_id, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (r.task_id, r.title, r.status, r.assignee_open_id, _to_text(r.updated_at))
                for r in records
            ],
        )
        self._conn.commit()
        return cur.rowcount

    def save_messages(self, records: Sequence[MessageRecord]) -> int:
        cur = self._conn.executemany(
            """
            INSERT OR IGNORE INTO message_records
                (msg_id, sender_open_id, content, created_at, chat_id, is_recalled)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r.msg_id,
                    r.sender_open_id,
                    r.content,
                    _to_text(r.created_at),
                    r.chat_id,
                    int(r.is_recalled),
                )
                for r in records
            ],
        )
        self._conn.commit()
        return cur.rowcount

    # ---------- 日报 ----------

    def save_report(self, report: DailyReport) -> None:
        body = json.dumps(
            {
                "scope": str(report.scope),
                "entity_id": report.entity_id,
                "report_date": report.report_date.isoformat(),
                "items": [
                    {
                        "source_type": i.source_type,
                        "source_id": i.source_id,
                        "text": i.text,
                        "occurred_at": _to_text(i.occurred_at),
                    }
                    for i in report.items
                ],
                "generated_at": _to_text(report.generated_at),
                "note": report.note,
            },
            ensure_ascii=False,
            default=_json_default,
        )
        self._conn.execute(
            """
            INSERT INTO daily_reports
                (scope, entity_id, report_date, generated_at, body_json, note)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(scope, entity_id, report_date) DO UPDATE SET
                generated_at=excluded.generated_at,
                body_json=excluded.body_json,
                note=excluded.note
            -- 降级保护：条目更少的新报告不得覆盖已存的更完整报告。
            -- 采集源临时失败时重新生成，否则会把好日报冲成「无数据」。
            WHERE json_array_length(excluded.body_json, '$.items')
               >= json_array_length(daily_reports.body_json, '$.items')
            """,
            (
                str(report.scope),
                report.entity_id,
                report.report_date.isoformat(),
                _to_text(report.generated_at),
                body,
                report.note,
            ),
        )
        self._conn.commit()

    def get_report(
        self, scope: ReportScope, entity_id: str, report_date: date
    ) -> DailyReport | None:
        row = self._conn.execute(
            "SELECT body_json FROM daily_reports "
            "WHERE scope=? AND entity_id=? AND report_date=?",
            (str(scope), entity_id, report_date.isoformat()),
        ).fetchone()
        return None if row is None else _decode_report(row[0])

    def list_reports(self, since: date, until: date) -> list[DailyReport]:
        rows = self._conn.execute(
            "SELECT body_json FROM daily_reports "
            "WHERE report_date >= ? AND report_date <= ? "
            "ORDER BY report_date, scope, entity_id",
            (since.isoformat(), until.isoformat()),
        ).fetchall()
        return [_decode_report(row[0]) for row in rows]

    # ---------- 运行摘要 ----------

    def save_run_summary(self, summary: RunSummary) -> None:
        # 幂等索引是「部分唯一索引」（只看 success/partial），
        # ON CONFLICT 无法定位它，因此先删同键旧行再插入。
        self._conn.execute(
            "DELETE FROM run_summaries WHERE team_id=? AND run_date=?",
            (summary.team_id, summary.run_date.isoformat()),
        )
        self._conn.execute(
            """
            INSERT INTO run_summaries
                (team_id, run_date, status, collected_json, sent_json,
                 failed_json, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                summary.team_id,
                summary.run_date.isoformat(),
                summary.status,
                json.dumps(summary.collected, ensure_ascii=False, default=_json_default),
                json.dumps(summary.sent, ensure_ascii=False, default=_json_default),
                json.dumps(summary.failed, ensure_ascii=False, default=_json_default),
                _to_text(summary.started_at),
                None if summary.finished_at is None else _to_text(summary.finished_at),
            ),
        )
        self._conn.commit()

    def find_latest_run(self, team_id: str, run_date: date) -> RunSummary | None:
        """返回该团队该日期的最近一次运行（任意状态），用于幂等判定。"""
        row = self._conn.execute(
            "SELECT status, collected_json, sent_json, failed_json, "
            "started_at, finished_at FROM run_summaries "
            "WHERE team_id=? AND run_date=? ORDER BY id DESC LIMIT 1",
            (team_id, run_date.isoformat()),
        ).fetchone()
        if row is None:
            return None
        return RunSummary(
            team_id=team_id,
            run_date=run_date,
            status=row[0],
            collected=json.loads(row[1]),
            sent=json.loads(row[2]),
            failed=json.loads(row[3]),
            started_at=_from_text(row[4]),
            finished_at=None if row[5] is None else _from_text(row[5]),
        )

    def find_successful_run(self, team_id: str, run_date: date) -> RunSummary | None:
        row = self._conn.execute(
            "SELECT collected_json, sent_json, failed_json, started_at, finished_at "
            "FROM run_summaries "
            "WHERE team_id=? AND run_date=? AND status='success'",
            (team_id, run_date.isoformat()),
        ).fetchone()
        if row is None:
            return None
        return RunSummary(
            team_id=team_id,
            run_date=run_date,
            status="success",
            collected=json.loads(row[0]),
            sent=json.loads(row[1]),
            failed=json.loads(row[2]),
            started_at=_from_text(row[3]),
            finished_at=None if row[4] is None else _from_text(row[4]),
        )


def _decode_report(body: str) -> DailyReport:
    data = json.loads(body)
    return DailyReport(
        scope=ReportScope(data["scope"]),
        entity_id=data["entity_id"],
        report_date=date.fromisoformat(data["report_date"]),
        items=[
            ReportItem(
                source_type=i["source_type"],
                source_id=i["source_id"],
                text=i["text"],
                occurred_at=_from_text(i["occurred_at"]),
            )
            for i in data["items"]
        ],
        generated_at=_from_text(data["generated_at"]),
        note=data.get("note"),
    )