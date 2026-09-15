"""Background execution helpers for the Time--Price Area Research panel.

The functions in this module deliberately do not import Streamlit.  A Streamlit
session owns the ``session_id`` passed to :func:`start_analysis_job`, while the
small process-local registry only owns worker state.  This keeps progress and
cancellation isolated when two users have the panel open at the same time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from concurrent.futures import Future, ThreadPoolExecutor
import hashlib
import json
import threading
import traceback
import uuid
from typing import Any, Callable, Mapping

import pandas as pd


class AnalysisCancelled(Exception):
    """Raised internally when a caller cancels an analysis."""


@dataclass
class JobState:
    """A thread-safe snapshot of one analysis worker."""

    job_id: str
    session_id: str
    config_signature: str
    status: str = "queued"
    fraction: float = 0.0
    message: str = "Queued"
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    future: Future | None = field(default=None, repr=False)

    def snapshot(self) -> dict[str, Any]:
        """Return a serialization-friendly immutable-ish status dictionary."""
        with self.lock:
            return {
                "job_id": self.job_id,
                "session_id": self.session_id,
                "config_signature": self.config_signature,
                "status": self.status,
                "fraction": float(self.fraction),
                "message": self.message,
                "result": self.result,
                "error": self.error,
                "created_at": self.created_at,
                "finished_at": self.finished_at,
                "cancel_requested": self.cancel_event.is_set(),
            }


_JOBS: dict[str, JobState] = {}
_JOBS_LOCK = threading.RLock()
_MAX_FINISHED_JOBS = 8
# Do not create one unbounded thread per browser click.  A queued Future can
# be cancelled before it starts, while active workers observe cancel_event.
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="area-lab")


def config_signature(config: Mapping[str, Any] | None) -> str:
    """Create a stable signature for duplicate-job detection and stale labels."""

    def _json_default(value: Any) -> str:
        if isinstance(value, (pd.Timestamp, datetime)):
            return value.isoformat()
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    payload = json.dumps(
        dict(config or {}),
        sort_keys=True,
        default=_json_default,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _set_progress(state: JobState, fraction: float, message: str) -> None:
    with state.lock:
        state.fraction = min(1.0, max(0.0, float(fraction)))
        state.message = str(message)
        if state.status == "queued":
            state.status = "running"


def _check_cancelled(state: JobState) -> None:
    if state.cancel_event.is_set():
        raise AnalysisCancelled("Analysis cancelled by the user.")


def _mark_cancelled(state: JobState, message: str) -> None:
    with state.lock:
        state.status = "cancelled"
        state.message = message
        state.error = message
        state.finished_at = datetime.now(timezone.utc)


def _prune_finished_locked() -> None:
    """Bound retained completed frames; active jobs are never removed."""
    finished = []
    for state in _JOBS.values():
        with state.lock:
            if state.status in {"completed", "cancelled", "error"}:
                finished.append(state)
    if len(finished) <= _MAX_FINISHED_JOBS:
        return
    finished.sort(
        key=lambda state: (
            state.finished_at or state.created_at
        ),
    )
    for state in finished[: len(finished) - _MAX_FINISHED_JOBS]:
        _JOBS.pop(state.job_id, None)


def _run_worker(
    state: JobState,
    ohlc: pd.DataFrame,
    config: Mapping[str, Any],
) -> None:
    """Build causal data and execute ``area_lab.models.run_lab``."""
    try:
        _set_progress(state, 0.02, "Building causal area features")
        _check_cancelled(state)

        # Lazy imports are intentional: the UI remains importable while the
        # feature/model modules are being developed or deployed independently.
        from .features import add_targets, build_features

        features = build_features(ohlc.copy(deep=True), dict(config))
        _check_cancelled(state)
        _set_progress(state, 0.28, "Adding purged forward targets")
        targets = add_targets(features, config.get("horizons", [1, 5, 10, 20]))
        _check_cancelled(state)
        _set_progress(state, 0.42, "Running chronological model evaluation")

        from .models import run_lab

        def progress(fraction: float, message: str) -> None:
            _check_cancelled(state)
            # The model owns the interval [0, 1]; reserve the first 42% for
            # feature construction so the UI reflects real worker progress.
            _set_progress(state, 0.42 + 0.56 * float(fraction), message)

        result = run_lab(
            targets,
            dict(config),
            progress=progress,
            cancel_event=state.cancel_event,
        )
        _check_cancelled(state)
        if not isinstance(result, dict):
            raise TypeError("area_lab.models.run_lab must return a dictionary.")

        # These frames are useful to the UI's audit/download ledger and do not
        # alter the documented model result keys.
        result = dict(result)
        result.setdefault("features", features)
        result.setdefault("labels", targets)
        result.setdefault("input_ohlc", ohlc.copy(deep=True))
        # Keep provenance beside (rather than inside) the documented result
        # frames.  The UI uses this immutable run metadata to prevent a result
        # from being presented as if it belonged to newer controls.
        metadata = result.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        metadata = dict(metadata)
        metadata.setdefault("config_hash", state.config_signature)
        metadata.setdefault("source", "SOXL yfinance history(period='max', auto_adjust=True)")
        metadata.setdefault("adjusted_prices", True)
        metadata.setdefault("completed_sessions_only", True)
        if not ohlc.empty:
            metadata.setdefault("source_start", pd.Timestamp(ohlc.index[0]).isoformat())
            metadata.setdefault("source_end", pd.Timestamp(ohlc.index[-1]).isoformat())
            metadata.setdefault("source_rows", int(len(ohlc)))
        metadata.setdefault(
            "reconstruction",
            "Rule-based causal anchors; future labels use each future date's own "
            "causal anchor and may reset. No chart pixels or manual anchors.",
        )
        result["metadata"] = metadata
        _set_progress(state, 1.0, "Analysis complete")
        with state.lock:
            state.result = result
            state.status = "completed"
            state.finished_at = datetime.now(timezone.utc)
    except AnalysisCancelled as exc:
        _mark_cancelled(state, str(exc))
    except InterruptedError as exc:
        # models.run_lab uses InterruptedError as its cancellation boundary.
        # It is a normal user action only when the event was actually set;
        # an unrelated InterruptedError remains a visible worker failure.
        if state.cancel_event.is_set():
            _mark_cancelled(state, str(exc) or "Analysis cancelled by the user.")
        else:
            with state.lock:
                state.status = "error"
                state.message = "Analysis failed"
                state.error = f"InterruptedError: {exc}"
                state.finished_at = datetime.now(timezone.utc)
            traceback.print_exc()
    except Exception as exc:  # worker failures must be visible, never silent
        detail = f"{type(exc).__name__}: {exc}"
        # Keep the traceback in the worker state for diagnostics, but expose a
        # concise explicit error to the UI.
        with state.lock:
            state.status = "error"
            state.message = "Analysis failed"
            state.error = detail
            state.finished_at = datetime.now(timezone.utc)
        traceback.print_exc()


def start_analysis_job(
    ohlc: pd.DataFrame,
    config: Mapping[str, Any],
    session_id: str | None = None,
) -> str:
    """Start a cancellable analysis worker and return its stable job id.

    A running/queued job with the same session and config is reused.  Finished
    jobs are not reused because pressing Analyze is an explicit request to
    rerun the study.
    """
    if not isinstance(ohlc, pd.DataFrame):
        raise TypeError("ohlc must be a pandas DataFrame.")
    session_id = str(session_id or "default")
    signature = config_signature(config)
    with _JOBS_LOCK:
        _prune_finished_locked()
        for state in _JOBS.values():
            if (
                state.session_id == session_id
                and state.config_signature == signature
                and state.status in {"queued", "running"}
            ):
                return state.job_id
        job_id = uuid.uuid4().hex
        state = JobState(job_id, session_id, signature)
        _JOBS[job_id] = state

    future = _EXECUTOR.submit(
        _run_worker,
        state,
        ohlc.copy(deep=True),
        dict(config),
    )
    with state.lock:
        state.future = future
    return job_id


def get_job(job_id: str | None) -> dict[str, Any] | None:
    """Return a current job snapshot, or ``None`` for an unknown id."""
    if not job_id:
        return None
    with _JOBS_LOCK:
        state = _JOBS.get(str(job_id))
    return state.snapshot() if state else None


def cancel_job(job_id: str | None) -> bool:
    """Request cancellation.  The worker checks the event between operations."""
    if not job_id:
        return False
    with _JOBS_LOCK:
        state = _JOBS.get(str(job_id))
    if state is None:
        return False
    with state.lock:
        if state.status in {"completed", "cancelled", "error"}:
            return False
        state.cancel_event.set()
        state.message = "Cancellation requested"
        future = state.future
        # A queued worker need not consume an executor slot just to discover
        # cancellation.  Running workers cannot be force-killed safely and
        # exit at their next causal/model cancellation check.
        if future is not None and future.cancel():
            _mark_cancelled(state, "Analysis cancelled before the worker started.")
    return True


def wait_for_job(job_id: str, timeout: float | None = None) -> dict[str, Any] | None:
    """Poll a job for non-Streamlit callers (primarily small unit tests)."""
    import time

    started = time.monotonic()
    while True:
        snapshot = get_job(job_id)
        if snapshot is None or snapshot["status"] in {
            "completed",
            "cancelled",
            "error",
        }:
            return snapshot
        if timeout is not None and time.monotonic() - started >= timeout:
            return snapshot
        time.sleep(0.01)


def clear_finished_jobs(session_id: str | None = None) -> None:
    """Release completed worker state; active jobs are deliberately retained."""
    with _JOBS_LOCK:
        for job_id, state in list(_JOBS.items()):
            with state.lock:
                terminal = state.status in {"completed", "cancelled", "error"}
                belongs = session_id is None or state.session_id == str(session_id)
            if terminal and belongs:
                _JOBS.pop(job_id, None)


def cleanup_registry() -> None:
    """Release the oldest finished result frames without touching active jobs."""
    with _JOBS_LOCK:
        _prune_finished_locked()


# Friendly aliases for callers that prefer generic job terminology.
start_job = start_analysis_job
get_job_status = get_job
run_lab_in_background = start_analysis_job
