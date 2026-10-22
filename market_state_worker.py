"""Supervised market-data worker. Run once to seed, or without args to poll.

Public market data only; no app import, UI calls, or session state. The
session-scoped PostgreSQL advisory lock is held for the full worker lifetime.
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import math
import signal
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from db import get_conn
from market_state_store import ensure_schema, load_state, save_state, _valid_state

LOG = logging.getLogger(__name__)
LOCK_ID = 736_853_001
HISTORY_INTERVAL = 300
MARKET_INTERVAL = 60
PROVIDER_TIMEOUT = 35
CYCLE_BUDGET = 55
OVERLAY_SYMBOLS = {
    "QQQ": "QQQ", "TQQQ": "TQQQ", "TLT": "TLT", "XLU": "XLU",
    "VIX": "^VIX", "SOX": "^SOX", "GUSH": "GUSH", "BTC": "BTC-USD",
}


class ProviderUnavailable(RuntimeError):
    pass


@contextmanager
def deadline(seconds=PROVIDER_TIMEOUT):
    """Hard wall-clock bound, including provider retries (worker main thread)."""
    def expired(_signum, _frame):
        raise TimeoutError("Market provider timeout")

    previous_handler = signal.signal(signal.SIGALRM, expired)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0]:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        return _jsonable(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _uncached(func):
    return getattr(func, "__wrapped__", func)


def download_history(symbol):
    if symbol == "SOXL":
        from data_providers import get_equity_history
        history = _uncached(get_equity_history)("SOXL")
        if history.empty:
            raise ProviderUnavailable()
        frame = history[["adj_close"]].rename(columns={"adj_close": "Close"})
        return frame
    import yfinance as yf
    frame = yf.Ticker(symbol).history(period="max", auto_adjust=True, timeout=20)
    if frame.empty or "Close" not in frame:
        raise ProviderUnavailable()
    frame = frame[["Close"]].copy()
    if frame.index.tz is not None:
        frame.index = frame.index.tz_localize(None)
    return frame


def _pack_history(frame):
    from landing_signal import completed_close_history
    closes = completed_close_history(frame)
    closes = closes[closes.map(lambda value: math.isfinite(float(value)))]
    if closes.empty:
        raise ProviderUnavailable()
    return {
        "dates": [date.strftime("%Y-%m-%d") for date in closes.index],
        "prices": [float(price) for price in closes],
    }


def _unpack_history(history):
    import pandas as pd
    return pd.DataFrame(
        {"Close": history["prices"]}, index=pd.to_datetime(history["dates"])
    )


def compute_signal(history):
    from landing_signal import compute_timeframe_readings, composite_signal
    from short_term_signal import load_manifest, short_term_ratings
    readings, closes = compute_timeframe_readings(_unpack_history(history))
    if closes.empty:
        raise ProviderUnavailable()
    manifest = load_manifest()
    ratings = short_term_ratings(closes, manifest=manifest)
    return _jsonable({
        "readings": readings.to_dict(orient="records"),
        "composite": composite_signal(readings),
        "close_date": closes.index[-1].strftime("%Y-%m-%d"),
        "short_rating": str(ratings.iloc[-1]),
        "manifest": manifest,
    })


def refresh_quote():
    from live_market_quote import fetch_live_quote
    return _uncached(fetch_live_quote)()


def refresh_feed():
    import chart_market_feed
    # During rollout the original provider may still have its old name. Once
    # the reader gateway is installed it must expose the refresh provider.
    provider = getattr(chart_market_feed, "refresh_chart_market_feed", None)
    if provider is None:
        provider = chart_market_feed.fetch_chart_market_feed
    return _uncached(provider)()


def refresh_snapshot(history, quote):
    from top_market_snapshot import compute_market_snapshot
    return compute_market_snapshot(_unpack_history(history), quote=quote)


def _component(state, name, operation, usable, now, *, timeout=PROVIDER_TIMEOUT):
    status = state["status"]["components"]
    old = status.get(name, {})
    try:
        if timeout <= 0:
            raise TimeoutError("Market refresh cycle budget exhausted")
        with deadline(timeout):
            value = operation()
        if not usable(value):
            raise ProviderUnavailable()
        state[name] = _jsonable(value)
        status[name] = {
            "last_success_at": now, "last_attempt_at": now, "stale": False,
        }
        return True
    except Exception as exc:
        # Only exception class names cross the persistence/logging boundary.
        error_type = type(exc).__name__
        status[name] = {
            **old, "last_attempt_at": now, "stale": True, "error": error_type,
        }
        LOG.warning("Market component %s unavailable: %s", name, error_type)
        return False


def recompute(previous=None, *, refresh_history=True):
    """Build a replacement without mutating previous; failures retain last-good."""
    now = _now()
    cycle_deadline = time.monotonic() + CYCLE_BUDGET
    state = copy.deepcopy(previous) if previous else {
        "version": 1, "history": {}, "quote": None,
        "market_feed": {"points": [], "error": "Market feed unavailable"},
        "snapshot": None, "signal": {}, "overlays": {},
    }
    state["status"] = {
        **state.get("status", {}),
        "source": "background-worker",
        "checked_at": now,
        "components": copy.deepcopy(state.get("status", {}).get("components", {})),
    }

    def update(target, name, operation, usable):
        return _component(
            target, name, operation, usable, now,
            timeout=min(PROVIDER_TIMEOUT, cycle_deadline - time.monotonic()),
        )

    if refresh_history or not state["history"]:
        # History and the signals based on it are committed together.
        def history_and_signal():
            history = _pack_history(download_history("SOXL"))
            return history, compute_signal(history)

        scratch = {"status": state["status"]}
        if update(scratch, "history", history_and_signal, bool):
            state["history"], state["signal"] = scratch["history"]
        elif not state["history"]:
            return None

    from live_market_quote import quote_error
    # A failed quote must replace the last good quote, never retain it silently.
    state["quote"] = quote_error("Polygon refresh unavailable.")
    if not update(state, "quote", refresh_quote, lambda value: isinstance(value, dict)):
        state["quote"] = quote_error("Polygon refresh failed: " +
            state["status"]["components"]["quote"].get("error", "Unknown error"))
    if state["quote"].get("error"):
        state["status"]["components"]["quote"]["stale"] = True
        state["status"]["components"]["quote"]["error"] = state["quote"]["error"]
    if state["quote"].get("price"):
        # Quote age is observation age, not worker age. Retained quotes cannot
        # become "live" just because another component was refreshed.
        try:
            observed = datetime.fromisoformat(state["quote"]["observed_at"].replace("Z", "+00:00"))
            state["quote"]["stale"] = (
                datetime.now(timezone.utc) - observed
            ).total_seconds() > 900 or state["status"]["components"]["quote"]["stale"]
        except (KeyError, ValueError, TypeError):
            state["quote"]["stale"] = True
    update(
        state, "market_feed", refresh_feed,
        lambda value: isinstance(value, dict) and bool(value.get("points")) and not value.get("error"),
    )
    if state["status"]["components"]["market_feed"]["stale"]:
        state["market_feed"]["error"] = "Market feed unavailable; retaining last-good prices."
    state["market_feed"]["quote"] = state["quote"]
    update(
        state, "snapshot", lambda: refresh_snapshot(state["history"], state["quote"]),
        lambda value: isinstance(value, dict) and (bool(value.get("current_price")) or bool(value.get("error"))),
    )
    # Lower-priority overlays cannot starve the one-minute quote/feed cycle.
    # Every configured symbol is attempted or gets an explicit timeout status.
    if refresh_history:
        for name, symbol in OVERLAY_SYMBOLS.items():
            scratch = {"status": state["status"]}
            component = "overlay_" + name
            if update(
                scratch, component,
                lambda symbol=symbol: _pack_history(download_history(symbol)), bool,
            ):
                state["overlays"][name] = scratch[component]
    state["status"]["stale"] = any(
        value.get("stale", False) for value in state["status"]["components"].values()
    )
    # Timestamp represents the newest successful build; component timestamps
    # separately expose old history/quotes/overlays during partial outages.
    state["computed_at"] = now
    state = _jsonable(state)
    json.dumps(state, allow_nan=False)
    return state if _valid_state(state) else None


@contextmanager
def worker_lock():
    """Yield None if another worker owns the session advisory lock."""
    conn = None
    try:
        conn = get_conn()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 3000")
            cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,))
            acquired = bool(cur.fetchone()[0])
        yield conn if acquired else None
    finally:
        # Closing the session always releases the lock, even on exceptions.
        if conn is not None:
            conn.close()


def _check_lock_connection(conn):
    # A lost session loses the advisory lock; fail rather than publish unlocked.
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()


def run(*, once=False):
    try:
        with worker_lock() as lock_conn:
            if lock_conn is None:
                LOG.warning("Market worker not started: WorkerAlreadyRunning")
                return 0 if load_state() is not None else 1
            ensure_schema()
            state = load_state()
            next_history = 0.0
            while True:
                started = time.monotonic()
                history_due = started >= next_history
                updated = recompute(state, refresh_history=history_due)
                _check_lock_connection(lock_conn)
                if updated is not None:
                    save_state(updated)
                    state = updated
                if once:
                    LOG.info("Market worker usable_state=%s", state is not None)
                    return 0 if state is not None else 1
                if history_due:
                    next_history = started + HISTORY_INTERVAL
                time.sleep(max(0, MARKET_INTERVAL - (time.monotonic() - started)))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        LOG.error("Market worker failed: %s", type(exc).__name__)
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Seed/refresh once then exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    return run(once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
