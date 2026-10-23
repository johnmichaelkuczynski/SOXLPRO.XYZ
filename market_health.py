"""Presentation of saved evidence only. No provider or database I/O."""
from datetime import datetime, timezone
from html import escape

HEARTBEAT_MAX_AGE = 180


def _age(stamp, now):
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return (now - parsed).total_seconds()
    except (TypeError, ValueError, AttributeError):
        return None


def diagnostic_lines(saved, evidence, now=None, latest=None):
    now = now or datetime.now(timezone.utc)
    saved = saved or {}
    read = evidence.get("status", "not_checked")
    messages = {
        "ok": "Successful; saved results read.",
        "empty": "Successful; no saved results found.",
        "failed": "Failed; current database contents could not be verified.",
        "timeout": "Timed out; current database contents could not be verified.",
        "busy": "Read already in progress; current database contents not yet verified.",
        "invalid_payload": "Read completed, but saved results were invalid.",
        "not_checked": "Not checked.",
    }
    lines = ["Database read: " + messages.get(read, "Unknown.") +
             " Checked: " + evidence.get("checked_at", "unavailable")]
    worker = evidence.get("worker") or {}
    heartbeat = worker.get("heartbeat_at")
    age = _age(heartbeat, now)
    # A failed read says nothing about whether the worker is running.
    if evidence.get("worker_read_status", "not_checked") != "ok":
        health = "Unknown; database read did not verify worker health."
    elif age is None or age < 0:
        health = "Unknown; no valid heartbeat available."
    elif age > HEARTBEAT_MAX_AGE:
        health = "Heartbeat overdue; current activity unverified."
    else:
        health = "Recent heartbeat verified (within 3 minutes)."
    lines.append("Background worker: " + health)
    lines.append("Last recorded heartbeat: " + (heartbeat or "unavailable") +
                 " · Phase: " + str(worker.get("phase", "unknown")))
    lines.append("Worker-health database read: " + evidence.get("worker_read_status", "not_checked"))
    lines.append("Displayed analysis snapshot: " + saved.get("computed_at", "unavailable") +
                 " · Daily close through: " + saved.get("signal", {}).get("close_date", "unavailable"))
    newer = latest and latest.get("computed_at") != saved.get("computed_at")
    lines.append("Results: " + (
        "Retained analysis snapshot; newer background results are available. "
        "Use Refresh to update the analysis; the chart has not been reset." if newer else
        "Retained saved results; not a fresh database read." if saved and
        (read != "ok" or saved.get("_read_warning")) else
        "Saved results; not a live calculation." if saved else "Unavailable."
    ))
    quote = saved.get("quote") or {}
    components = saved.get("status", {}).get("components", {})
    quote_age = _age(quote.get("observed_at"), now)
    current = (not newer and read == "ok" and quote_age is not None and 0 <= quote_age <= 900
               and not quote.get("stale") and not components.get("quote", {}).get("stale"))
    lines.append("Quote in this analysis snapshot (the market strip refreshes separately): " + (
        "Current timestamped observation (within 15 minutes)." if current else
        "Retained observation; not verified current." if quote else "Unavailable."
    ) + " Observed: " + str(quote.get("observed_at", "unavailable")))
    lines.append("Latest background component updates (not a claim that the chart refreshed):")
    components = (latest or saved).get("status", {}).get("components", {})
    for name, status in components.items():
        label = {"history": "Daily history and signal", "quote": "Quote",
                 "snapshot": "Market snapshot", "market_feed": "Intraday feed"}.get(
                     name, name.replace("overlay_", "Overlay "))
        outcome = "Latest update failed; retained data where available." if status.get("stale") else "Latest update succeeded."
        lines.append(f"{label}: {outcome} Last success: "
                     f"{status.get('last_success_at', 'unavailable')}. Last attempt: "
                     f"{status.get('last_attempt_at', 'unavailable')}.")
    if not components:
        lines.append("Component update history: unavailable.")
    return lines


def diagnostics_html(saved, evidence):
    return ("<details><summary>Background updates &amp; saved data</summary>" +
            "".join("<p>" + escape(line) + "</p>" for line in diagnostic_lines(saved, evidence)) +
            "</details>")


def render_diagnostics(saved, latest=None):
    import streamlit as st
    from market_state_store import read_health
    with st.expander("Background updates & saved data", expanded=False):
        for line in diagnostic_lines(saved, read_health(refresh=True), latest=latest):
            st.text(line)
