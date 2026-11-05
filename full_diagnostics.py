"""Bounded, read-only diagnostics jobs; no market refreshes or account mutations."""
from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import tornado.web

ROOT = Path(__file__).resolve().parent
TEST_GROUPS = {
    "Daily signals": ["test_landing_signal.py", "test_short_term_signal.py"],
    "Price slider": ["test_continuous_price_model.py"],
    "Chart data and projections": ["test_chart_payload.py", "test_chart_projection_probability.py",
                                   "test_chart_projection_hover.py", "test_chart_market_feed.py"],
    "Options pricing and validation": ["test_options_projection.py", "test_options_validation.py"],
    "Mean reversion": ["test_mean_reversion_model.py"],
    "Area research": ["test_area_lab_features.py", "test_area_lab_models.py"],
    "Channel research": ["test_channel_walk_forward.py", "test_channel_report_ui.py"],
    "Call risk/reward": ["test_call_risk_reward.py"],
    "Public access": ["test_public_access.py"],
}
_jobs = {}
_lock = threading.Lock()
_active = None
COOLDOWN = 60


def result(name, group, status, detail):
    return {"name": name, "group": group, "status": status, "detail": str(detail)}


def _run_check(name, group, fn):
    start = time.monotonic()
    try:
        status, detail = fn()
        row = result(name, group, status, detail)
    except Exception as exc:
        # Never return provider exception strings, URLs, credentials or tracebacks.
        row = result(name, group, "fail", f"{type(exc).__name__}: check failed. No private values are included.")
    row["ms"] = round((time.monotonic() - start) * 1000)
    return row


def _http(url):
    import requests
    response = requests.get(url, timeout=8, allow_redirects=False)
    return ("pass" if response.status_code == 200 else "fail",
            f"GET {response.request.path_url}: HTTP {response.status_code}")


def _database_snapshot():
    from db import get_conn
    from market_state_store import _valid_state
    connection = get_conn()
    try:
        connection.set_session(readonly=True, autocommit=True)
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = 3000")
            cursor.execute("SELECT payload FROM market_state WHERE id = 1")
            row = cursor.fetchone()
            if not row or not _valid_state(row[0]):
                raise ValueError("Missing or invalid snapshot")
            state = row[0]
            try:
                cursor.execute("SELECT payload FROM market_worker_health WHERE id = 1")
                heartbeat = cursor.fetchone()
            except Exception:
                heartbeat = None
        return state, heartbeat[0] if heartbeat else {}
    finally:
        connection.close()


def _saved_checks():
    rows = []
    try:
        state, heartbeat = _database_snapshot()
        rows.append(result("Fresh database read", "Saved data", "pass",
                           "Read-only SELECT returned a valid saved analysis snapshot."))
    except Exception as exc:
        rows.append(result("Fresh database read", "Saved data", "fail",
                           f"{type(exc).__name__}; current database contents could not be verified."))
        from market_state_store import _read_disk_snapshot
        state = _read_disk_snapshot()
        heartbeat = {}
        rows.append(result("Last-known snapshot fallback", "Saved data",
                           "pass" if state else "fail",
                           "A saved fallback is available; this is NOT a successful database read."
                           if state else "No usable fallback snapshot."))
    if not state:
        return rows
    history = state.get("history", {})
    prices, dates = history.get("prices", []), history.get("dates", [])
    rows.append(result("SOXL history", "Saved data", "pass" if len(prices) >= 252 else "fail",
                       f"{len(prices)} daily prices; latest close date {dates[-1] if dates else 'unavailable'}."))
    signal = state.get("signal") or {}
    rows.append(result("Saved daily signals", "Saved data",
                       "pass" if signal.get("composite") and signal.get("close_date") else "fail",
                       f"Signal close date: {signal.get('close_date', 'unavailable')}."))
    for name in ["QQQ", "TQQQ", "TLT", "XLU", "VIX", "SOX", "GUSH", "BTC"]:
        overlay = (state.get("overlays") or {}).get(name) or {}
        values, stamps = overlay.get("prices", []), overlay.get("dates", [])
        valid = (len(values) >= 2 and len(values) == len(stamps)
                 and all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in values))
        rows.append(result(name + " saved history", "Benchmarks", "pass" if valid else "fail",
                           f"{len(values)} saved prices; through {stamps[-1] if stamps else 'unavailable'}."))
    for name in ["quote", "snapshot", "market_feed"]:
        rows.append(result(name.replace("_", " ").title(), "Saved data",
                           "pass" if state.get(name) else "fail",
                           "Saved data present; freshness is checked separately." if state.get(name)
                           else "This saved component is missing."))
    for name, item in (state.get("status", {}).get("components") or {}).items():
        rows.append(result(name + " last refresh", "Background updates",
                           "fail" if item.get("stale") else "pass",
                           f"Last successful update: {item.get('last_success_at', 'unavailable')}; "
                           f"last attempt: {item.get('last_attempt_at', 'unavailable')}."))
    try:
        age = (datetime.now(timezone.utc) -
               datetime.fromisoformat(heartbeat["heartbeat_at"].replace("Z", "+00:00"))).total_seconds()
        rows.append(result("Background worker heartbeat", "Background updates",
                           "pass" if 0 <= age <= 180 else "fail",
                           f"Database-recorded heartbeat is {round(age)} seconds old."))
    except (KeyError, ValueError, TypeError):
        rows.append(result("Background worker heartbeat", "Background updates", "not_tested",
                           "A current worker heartbeat could not be verified."))
    quote = state.get("quote") or {}
    try:
        age = (datetime.now(timezone.utc) -
               datetime.fromisoformat(quote["observed_at"].replace("Z", "+00:00"))).total_seconds()
        rows.append(result("SOXL quote observation age", "Freshness",
                           "pass" if 0 <= age <= 900 and not quote.get("stale") else "warning",
                           f"Observation is {round(age / 60, 1)} minutes old. Closed markets can explain age; "
                           "a stored quote is not guaranteed real-time."))
    except (KeyError, ValueError, TypeError):
        rows.append(result("SOXL quote observation age", "Freshness", "fail", "No valid observation timestamp."))
    return rows


def _provider(symbol):
    import requests
    response = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                            params={"range": "5d", "interval": "1d"},
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    if response.status_code != 200:
        return "fail", f"Live Yahoo history request returned HTTP {response.status_code}."
    records = response.json().get("chart", {}).get("result") or []
    valid = bool(records and records[0].get("timestamp"))
    return ("pass" if valid else "fail",
            f"Live provider request returned {len(records[0].get('timestamp', [])) if records else 0} daily observations. "
            "This is not a real-time quote check.")


def _options():
    from options_projection_data import load_chain
    today = datetime.now(timezone.utc).date()
    expiration = today + timedelta(days=((4 - today.weekday()) % 7) or 7)
    contracts = load_chain(expiration, "call")
    quoted = sum(1 for c in contracts if isinstance(c.get("bid"), (int, float))
                 and isinstance(c.get("ask"), (int, float)) and c["ask"] >= c["bid"] >= 0)
    return ("pass" if quoted else "fail",
            f"Polygon {expiration} calls: {len(contracts)} contracts, {quoted} with bid/ask. "
            "Provider cache may be reused for up to 60 seconds.")


def _ai(provider):
    if provider == "OpenAI":
        from openai_client import get_openai_client, DEFAULT_MODEL
        client = get_openai_client().with_options(timeout=15, max_retries=0)
        answer = client.chat.completions.create(
            model=DEFAULT_MODEL, messages=[{"role": "user", "content": "Reply with the word OK only."}],
            max_completion_tokens=256)
        text = answer.choices[0].message.content or ""
    else:
        from anthropic_client import get_anthropic_client
        client = get_anthropic_client().with_options(timeout=15, max_retries=0)
        answer = client.messages.create(model="claude-sonnet-4-5", max_tokens=16,
                                       messages=[{"role": "user", "content": "Reply with the word OK only."}])
        text = "".join(getattr(block, "text", "") for block in answer.content)
    return ("pass" if "OK" in text.upper() else "fail",
            "A real test prompt returned OK." if "OK" in text.upper()
            else "The test did not return the expected answer; chat is not verified.")


def _regressions():
    try:
        completed = subprocess.run([sys.executable, str(ROOT / "diagnostics_test_runner.py")],
                                   cwd=ROOT, capture_output=True, text=True, timeout=120)
        line = next(line for line in reversed(completed.stdout.splitlines())
                    if line.startswith("SOXL_DIAGNOSTICS="))
        return json.loads(line.split("=", 1)[1])
    except (OSError, StopIteration, ValueError, subprocess.TimeoutExpired):
        return [result("Automated feature regression checks", "Regression tests", "not_tested",
                       "The fixed test runner is unavailable or exceeded its 120-second budget. "
                       "These features are NOT verified by this run.")]


def _append(job, rows):
    with _lock:
        job["checks"].extend(rows)


def _work(job, base_url):
    try:
        checks = [
            ("Public page", "HTTP", lambda: _http(base_url + "/")),
            ("Gateway readiness", "HTTP", lambda: _http(base_url + "/_gateway/ready")),
            ("Interactive server", "HTTP", lambda: _http(base_url + "/_stcore/health")),
            ("Polygon options chain and quotes", "Live services", _options),
            ("OpenAI answer generation", "Live services", lambda: _ai("OpenAI")),
            ("Anthropic answer generation", "Live services", lambda: _ai("Anthropic")),
        ]
        for symbol in ["SOXL", "QQQ", "TQQQ", "TLT", "XLU", "^VIX", "^SOX", "GUSH", "BTC-USD"]:
            checks.append((symbol + " history provider", "Live services", lambda s=symbol: _provider(s)))
        # Four bounded network calls at a time; the main app is not rerun or stopped.
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(_run_check, *item) for item in checks]
            futures.extend([pool.submit(_saved_checks), pool.submit(_regressions)])
            for future in as_completed(futures):
                try:
                    rows = future.result()
                    _append(job, rows if isinstance(rows, list) else [rows])
                except Exception as exc:
                    _append(job, [result("Diagnostic subsystem", "Diagnostics", "fail", type(exc).__name__)])
        _append(job, [result("Scope and safety", "Coverage", "not_tested",
                            "No orders, payments, account changes, emails, or destructive actions were performed. "
                            "Regression tests use controlled fixtures. Forecast accuracy and every possible "
                            "market condition cannot be certified by a health check.")])
    finally:
        with _lock:
            job["running"] = False
            job["finished_at"] = datetime.now(timezone.utc).isoformat()


def start_job(base_url):
    global _active
    with _lock:
        if _active in _jobs:
            previous = _jobs[_active]
            if previous["running"] or time.monotonic() - previous["_started"] < COOLDOWN:
                return _active
        job_id = uuid.uuid4().hex
        job = {"id": job_id, "running": True, "checks": [],
               "started_at": datetime.now(timezone.utc).isoformat(), "_started": time.monotonic()}
        _jobs[job_id] = job
        _active = job_id
        for old in list(_jobs)[:-5]:
            del _jobs[old]
    threading.Thread(target=_work, args=(job, base_url), daemon=True, name="full-app-diagnostics").start()
    return job_id


class DiagnosticsRun(tornado.web.RequestHandler):
    def initialize(self, port):
        self.port = port

    def post(self):
        from urllib.parse import urlsplit
        origin = self.request.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.request.host:
            self.set_status(403)
            self.finish({"error": "Use the diagnostics button in this app."})
            return
        if not self.request.headers.get("Content-Type", "").startswith("application/json"):
            self.set_status(415)
            self.finish({"error": "JSON requests required."})
            return
        self.set_header("Cache-Control", "no-store")
        self.finish({"id": start_job(f"http://127.0.0.1:{self.port}")})


class DiagnosticsStatus(tornado.web.RequestHandler):
    def get(self, job_id):
        with _lock:
            job = _jobs.get(job_id)
            report = {k: v for k, v in job.items() if not k.startswith("_")} if job else None
        self.set_header("Cache-Control", "no-store")
        if report is None:
            self.set_status(404)
            self.finish({"error": "Run not found; start a new check."})
        else:
            self.finish(report)
