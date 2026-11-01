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
import os
import threading
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from db import get_conn

LOG = logging.getLogger(__name__)
READ_BUDGET_SECONDS = 0.8
STATEMENT_TIMEOUT_MS = 500
_read_slot = threading.Lock()
_last_good = None
_read_health = {"status": "not_checked"}
_worker_health = None
_worker_read_status = "not_checked"
_health_slot = threading.Lock()
_DISK_SNAPSHOT = Path(tempfile.gettempdir()) / "soxl-last-market-state.json"
_BUNDLED_SNAPSHOT = Path(__file__).resolve().parent / "data" / "last_known_market_state.json"


def _save_disk_snapshot(payload):
    """Best-effort same-instance fallback; never include credentials or user data."""
    try:
        temporary = _DISK_SNAPSHOT.with_suffix(".tmp")
        temporary.write_text(json.dumps(_clean_json(payload), allow_nan=False))
        os.replace(temporary, _DISK_SNAPSHOT)
    except (OSError, TypeError, ValueError):
        LOG.warning("Local last-market snapshot could not be saved.")


def _read_disk_snapshot():
    for path in (_DISK_SNAPSHOT, _BUNDLED_SNAPSHOT):
        try:
            payload = json.loads(path.read_text())
            if _valid_state(payload):
                return payload
        except (OSError, ValueError, TypeError):
            continue
    return None


def read_health(*, refresh=False):
    """Last database-read evidence in this process; never a worker liveness probe."""
    if refresh:
        _refresh_worker_health()
    return copy.deepcopy({**_read_health, "worker": _worker_health,
                          "worker_read_status": _worker_read_status})


def _refresh_worker_health():
    """Optional, independently bounded read; never gates saved market results."""
    global _worker_read_status
    if not _health_slot.acquire(blocking=False):
        _worker_read_status = "busy"
        return
    done = threading.Event()

    def read():
        global _worker_health, _worker_read_status
        try:
            row = _execute("SELECT payload FROM market_worker_health WHERE id = 1", fetch=True)
            _worker_health = row[0] if row else None
            _worker_read_status = "ok"
        except StateStoreError:
            _worker_read_status = "failed"
        finally:
            _health_slot.release()
            done.set()

    threading.Thread(target=read, name="market-health-read", daemon=True).start()
    if not done.wait(READ_BUDGET_SECONDS):
        _worker_read_status = "timeout"


def _record_read(status):
    global _read_health
    _read_health = {"status": status, "checked_at": datetime.now(timezone.utc).isoformat()}


def _retained_state(reason):
    global _last_good
    if _last_good is None:
        _last_good = _read_disk_snapshot()
    if _last_good is None:
        return None
    result = copy.deepcopy(_last_good)
    result["_read_warning"] = reason
    return result

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
    try:
        _execute("""
            CREATE TABLE IF NOT EXISTS market_worker_health (
                id SMALLINT PRIMARY KEY CHECK (id = 1),
                payload JSONB NOT NULL
            )
        """, timeout_ms=3000)
    except StateStoreError:
        LOG.warning("Optional worker-health schema unavailable; market updates will continue.")


def save_worker_health(phase):
    """Worker-only heartbeat, independent of successful market downloads."""
    _execute(
        "INSERT INTO market_worker_health (id, payload) VALUES (1, %s::jsonb) "
        "ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload",
        (json.dumps({"heartbeat_at": datetime.now(timezone.utc).isoformat(),
                     "phase": phase}),), timeout_ms=3000,
    )


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
    global _last_good
    _last_good = copy.deepcopy(_clean_json(payload))
    _save_disk_snapshot(_last_good)


def load_state():
    """Return a validated version-1 state or None, in at most ~800ms.

    Missing schema/unavailable DB is an explicit sanitized warning, not an
    attempt to create schema. Only one bounded database read can be in flight.
    """
    if not _read_slot.acquire(blocking=False):
        _record_read("busy")
        LOG.warning("Market state read unavailable: ReadBusy")
        return _retained_state("Database read in progress; showing saved results.")
    done = threading.Event()
    result = []

    def read():
        global _last_good
        try:
            row = _execute("SELECT payload FROM market_state WHERE id = 1", fetch=True)
            if row and _valid_state(row[0]):
                # Retain even a response that arrives after the request's budget.
                # Assignment is atomic; returned objects are always deep copies.
                _last_good = copy.deepcopy(row[0])
                _save_disk_snapshot(_last_good)
                result.append(row[0])
                _record_read("ok")
            elif row and row[0] is not None:
                _record_read("invalid_payload")
                LOG.warning("Market state read unavailable: InvalidPayload")
            else:
                _record_read("empty")
        except StateStoreError as exc:
            _record_read("failed")
            LOG.warning("Market state read unavailable: %s", exc)
        finally:
            _read_slot.release()
            done.set()

    threading.Thread(target=read, name="market-state-read", daemon=True).start()
    if not done.wait(READ_BUDGET_SECONDS):
        _record_read("timeout")
        LOG.warning("Market state read unavailable: ReadTimeout")
        return _retained_state("Database response delayed; showing saved results.")
    return copy.deepcopy(result[0]) if result else _retained_state(
        "Database update unavailable; showing saved results.")


def request_refresh():
    """Nonblocking hint API; the supervised worker polls every minute.

    Deliberately does not connect, spawn jobs, or download on a request path.
    False indicates no immediate refresh was scheduled.
    """
    return False
