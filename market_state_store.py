"""Small PostgreSQL reader/writer for public market state (no market/UI imports).

Only the worker calls ensure_schema. Readers never perform DDL or downloads.
db.get_conn owns the existing database configuration; it has a 15s connect
timeout, so request reads additionally have a bounded, single-flight daemon
thread. A slow connection is eventually closed without holding up a request.
"""
from __future__ import annotations

import copy
import json
import logging
import math
import threading
from datetime import datetime

from db import get_conn

LOG = logging.getLogger(__name__)
READ_BUDGET_SECONDS = 0.8
STATEMENT_TIMEOUT_MS = 500
_read_slot = threading.Lock()
_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_state (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    payload JSONB NOT NULL CHECK (payload->>'version' = '1'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


class StateStoreError(RuntimeError):
    """A deliberately credential-free persistence error."""


def _clean_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _clean_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_clean_json(item) for item in value]
    return value


def _valid_state(payload):
    if not isinstance(payload, dict) or type(payload.get("version")) is not int:
        return False
    if payload["version"] != 1:
        return False
    try:
        stamp = datetime.fromisoformat(payload["computed_at"].replace("Z", "+00:00"))
        if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
            return False
        history = payload["history"]
        dates, prices = history["dates"], history["prices"]
        if not isinstance(dates, list) or not isinstance(prices, list):
            return False
        if not dates or len(dates) != len(prices):
            return False
        for date, price in zip(dates, prices):
            if datetime.strptime(date, "%Y-%m-%d").strftime("%Y-%m-%d") != date:
                return False
            if isinstance(price, bool) or not isinstance(price, (int, float)):
                return False
            if not math.isfinite(price) or price <= 0:
                return False
        if dates != sorted(set(dates)):
            return False
        signal = payload["signal"]
        return (
            isinstance(signal["readings"], list)
            and isinstance(signal["composite"], dict)
            and isinstance(signal["short_rating"], str)
            and isinstance(signal["manifest"], dict)
            and signal["close_date"] <= dates[-1]
            and isinstance(payload["overlays"], dict)
            and isinstance(payload["market_feed"], dict)
            and isinstance(payload["snapshot"], dict)
            and (payload["quote"] is None or isinstance(payload["quote"], dict))
        )
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return False


def _execute(sql, params=None, *, fetch=False, timeout_ms=STATEMENT_TIMEOUT_MS):
    conn = None
    try:
        conn = get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout = %s", (timeout_ms,))
                cur.execute("SET LOCAL lock_timeout = %s", (timeout_ms,))
                cur.execute(sql, params)
                return cur.fetchone() if fetch else None
    except Exception as exc:
        # Never include the driver message, DSN, SQL parameters or traceback.
        raise StateStoreError(type(exc).__name__) from None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                LOG.warning("Market state connection disposal failed: CloseError")


def ensure_schema():
    """Explicit worker/setup operation; never called by load_state/save_state."""
    _execute(_SCHEMA, timeout_ms=3000)


def save_state(payload):
    """Atomically replace the single last-good record, rejecting unusable input."""
    if not _valid_state(payload):
        raise ValueError("Invalid market state version 1 payload")
    try:
        serialized = json.dumps(_clean_json(payload), allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError("Market state must be JSON serializable") from None
    _execute(
        "INSERT INTO market_state (id, payload, updated_at) VALUES (1, %s::jsonb, now()) "
        "ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()",
        (serialized,),
        timeout_ms=3000,
    )


def load_state():
    """Return a validated version-1 state or None, in at most ~800ms.

    Missing schema/unavailable DB is an explicit sanitized warning, not an
    attempt to create schema. Only one bounded database read can be in flight.
    """
    if not _read_slot.acquire(blocking=False):
        LOG.warning("Market state read unavailable: ReadBusy")
        return None
    done = threading.Event()
    result = []

    def read():
        try:
            row = _execute("SELECT payload FROM market_state WHERE id = 1", fetch=True)
            if row and _valid_state(row[0]):
                result.append(row[0])
            elif row:
                LOG.warning("Market state read unavailable: InvalidPayload")
        except StateStoreError as exc:
            LOG.warning("Market state read unavailable: %s", exc)
        finally:
            _read_slot.release()
            done.set()

    threading.Thread(target=read, name="market-state-read", daemon=True).start()
    if not done.wait(READ_BUDGET_SECONDS):
        LOG.warning("Market state read unavailable: ReadTimeout")
        return None
    return copy.deepcopy(result[0]) if result else None


def request_refresh():
    """Nonblocking hint API; the supervised worker polls every minute.

    Deliberately does not connect, spawn jobs, or download on a request path.
    False indicates no immediate refresh was scheduled.
    """
    return False
