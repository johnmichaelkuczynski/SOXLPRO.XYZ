"""Neon Postgres persistence layer for the SOXL app.

Uses the external Neon database via the DATABASE_URL secret. Stores diagnostic
runs, synthetic-user sessions, and quality-control results so the three
diagnostic functions have a durable audit trail.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Optional

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def db_available() -> bool:
    return bool(DATABASE_URL)


def get_conn():
    """Open a fresh connection to Neon. Caller is responsible for closing."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set — Neon database unavailable.")
    dsn = DATABASE_URL
    if "sslmode=" not in dsn:
        dsn += ("&" if "?" in dsn else "?") + "sslmode=require"
    return psycopg2.connect(dsn, connect_timeout=15)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS diagnostic_runs (
    id          BIGSERIAL PRIMARY KEY,
    run_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind        TEXT NOT NULL,
    ok          BOOLEAN,
    totals      JSONB,
    report      JSONB,
    user_email  TEXT
);

CREATE TABLE IF NOT EXISTS synthetic_user_sessions (
    id          BIGSERIAL PRIMARY KEY,
    run_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    persona     TEXT,
    prompt      TEXT,
    response    TEXT,
    transcript  JSONB,
    outcome     JSONB,
    user_email  TEXT
);

CREATE TABLE IF NOT EXISTS qc_results (
    id              BIGSERIAL PRIMARY KEY,
    run_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    subject         TEXT,
    source_text     TEXT,
    openai_verdict  JSONB,
    gptzero         JSONB,
    legitimate      BOOLEAN,
    score           DOUBLE PRECISION,
    user_email      TEXT
);
"""

_initialized = False


def init_db() -> None:
    """Create tables if they don't exist. Idempotent; runs once per process."""
    global _initialized
    if _initialized:
        return
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(_SCHEMA)
        _initialized = True
    finally:
        conn.close()


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


def save_diagnostic_run(kind: str, ok: bool, totals: dict, report: dict,
                        user_email: Optional[str] = None) -> Optional[int]:
    try:
        init_db()
        conn = get_conn()
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO diagnostic_runs (kind, ok, totals, report, user_email) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (kind, ok, _json(totals), _json(report), user_email),
                )
                return cur.fetchone()[0]
        finally:
            conn.close()
    except Exception:
        return None


def save_synthetic_session(persona: str, prompt: str, response: str,
                           transcript: Any, outcome: Any,
                           user_email: Optional[str] = None) -> Optional[int]:
    try:
        init_db()
        conn = get_conn()
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO synthetic_user_sessions "
                    "(persona, prompt, response, transcript, outcome, user_email) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                    (persona, prompt, response, _json(transcript), _json(outcome), user_email),
                )
                return cur.fetchone()[0]
        finally:
            conn.close()
    except Exception:
        return None


def save_qc_result(subject: str, source_text: str, openai_verdict: Any,
                   gptzero: Any, legitimate: Optional[bool], score: Optional[float],
                   user_email: Optional[str] = None) -> Optional[int]:
    try:
        init_db()
        conn = get_conn()
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO qc_results "
                    "(subject, source_text, openai_verdict, gptzero, legitimate, score, user_email) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (subject, source_text, _json(openai_verdict), _json(gptzero),
                     legitimate, score, user_email),
                )
                return cur.fetchone()[0]
        finally:
            conn.close()
    except Exception:
        return None


def recent_rows(table: str, limit: int = 10) -> list[dict]:
    """Fetch recent rows from one of the known tables as plain dicts."""
    allowed = {"diagnostic_runs", "synthetic_user_sessions", "qc_results"}
    if table not in allowed:
        raise ValueError(f"unknown table: {table}")
    try:
        init_db()
        conn = get_conn()
        try:
            with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(f"SELECT * FROM {table} ORDER BY run_at DESC LIMIT %s", (limit,))
                return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception:
        return []


def ping() -> dict:
    """Connectivity check used by the system diagnostic."""
    t0 = datetime.utcnow()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            version = cur.fetchone()[0]
    finally:
        conn.close()
    ms = int((datetime.utcnow() - t0).total_seconds() * 1000)
    return {"version": version, "ms": ms}
