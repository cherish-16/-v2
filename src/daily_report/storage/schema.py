"""SQLite 建表 DDL。

全部语句幂等（IF NOT EXISTS），可重复执行。
"""

from __future__ import annotations

import sqlite3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS members (
    member_id      TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    github_login   TEXT,
    feishu_open_id TEXT,
    email          TEXT,
    git_emails     TEXT
);

CREATE TABLE IF NOT EXISTS commit_records (
    sha          TEXT PRIMARY KEY,
    author_login TEXT NOT NULL,
    message      TEXT NOT NULL,
    committed_at TEXT NOT NULL,
    repo         TEXT NOT NULL,
    author_email TEXT
);

CREATE TABLE IF NOT EXISTS task_records (
    task_id          TEXT PRIMARY KEY,
    title            TEXT NOT NULL,
    status           TEXT NOT NULL,
    assignee_open_id TEXT,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS message_records (
    msg_id           TEXT PRIMARY KEY,
    sender_open_id   TEXT,
    content          TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    chat_id          TEXT NOT NULL,
    is_recalled      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    scope        TEXT NOT NULL,
    entity_id    TEXT NOT NULL,
    report_date  TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    body_json    TEXT NOT NULL,
    note         TEXT,
    UNIQUE (scope, entity_id, report_date)
);

CREATE TABLE IF NOT EXISTS run_summaries (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id        TEXT NOT NULL,
    run_date       TEXT NOT NULL,
    status         TEXT NOT NULL,
    collected_json TEXT NOT NULL,
    sent_json      TEXT NOT NULL,
    failed_json    TEXT NOT NULL,
    started_at     TEXT NOT NULL,
    finished_at    TEXT
);

-- 幂等约束：同一团队同一天只允许一条「有产出」的记录。
-- success 与 partial 都算有产出（partial 已经发过邮件），必须唯一，
-- 否则重触发会二次发信。failed 不在此列 —— 全渠道失败后允许当日重试。
CREATE UNIQUE INDEX IF NOT EXISTS idx_run_productive_unique
    ON run_summaries (team_id, run_date)
    WHERE status IN ('success', 'partial');

DROP INDEX IF EXISTS idx_run_success_unique;
"""


def init_db(path: str) -> sqlite3.Connection:
    """打开（或创建）数据库并确保表结构就绪。"""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn