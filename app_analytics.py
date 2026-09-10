"""Privacy-preserving application analytics.

The deployed application receives Umami from Replit.  This module only
validates the small set of events that the application is allowed to emit and
hands them to the parent-page bridge; it never adds a tracker or makes an HTTP
request.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Mapping

import streamlit as st
import streamlit.components.v1 as components

from auth import is_development_preview


# These are deliberately explicit.  In particular, accepting a generic
# ``dict[str, Any]`` here would make it too easy to accidentally send a
# prompt, an identity, a checkout/session id, or a URL.
SERVER_EVENT_SPECS: dict[str, dict[str, frozenset[str]]] = {
    "checkout_ready": {"location": frozenset({"buy_dialog"})},
    "checkout_error": {"stage": frozenset({"checkout", "confirmation"})},
    "checkout_cancelled": {"location": frozenset({"return"})},
    "payment_confirmed": {"plan": frozenset({"full_access"})},
    "signed_in_session": {"tier": frozenset({"signed_in", "paid"})},
    "market_question_submitted": {"feature": frozenset({"market_chat"})},
    "market_answer_received": {"feature": frozenset({"market_chat"})},
    "strategy_requested": {"feature": frozenset({"strategy_builder"})},
    "strategy_generated": {"feature": frozenset({"strategy_builder"})},
}

# Public alias useful to callers and to tests, while keeping the server
# allowlist distinct from the browser-only click events in bridge.js.
EVENT_SPECS = SERVER_EVENT_SPECS

QUEUE_KEY = "_analytics_pending_events"
ONCE_KEYS_KEY = "_analytics_once_key_hashes"
SEQUENCE_KEY = "_analytics_event_sequence"
BRIDGE_PATH = Path(__file__).resolve().parent / "components" / "analytics" / "bridge.js"

_MAX_ONCE_KEYS = 512
_MAX_PENDING_EVENTS = 256


def _preview_is_active() -> bool:
    """Return the preview flag without allowing analytics to break the app."""

    try:
        return bool(is_development_preview())
    except Exception:
        # Instrumentation is fail-closed when deployment information cannot be
        # read.  A broken analytics check must never affect the app.
        return True


def _session_get(key: str, default: Any) -> Any:
    try:
        return st.session_state.get(key, default)
    except Exception:
        return default


def _session_set(key: str, value: Any) -> bool:
    try:
        st.session_state[key] = value
        return True
    except Exception:
        return False


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _hash_once_key(once_key: Any) -> str:
    """Hash a deduplication key; the key itself never enters the queue."""

    if isinstance(once_key, str):
        encoded = once_key.encode("utf-8")
    else:
        encoded = _canonical_json(once_key).encode("utf-8")
    return hashlib.sha256(b"soxl-analytics-once:" + encoded).hexdigest()


def _valid_properties(name: Any, properties: Any) -> bool:
    spec = SERVER_EVENT_SPECS.get(name)
    if spec is None or not isinstance(properties, Mapping):
        return False
    if set(properties) != set(spec):
        return False
    for key, allowed_values in spec.items():
        value = properties.get(key)
        if not isinstance(value, str) or value not in allowed_values:
            return False
    return True


def _validated_event(name: Any, properties: Any, event_id: Any = None) -> bool:
    if not isinstance(name, str) or not _valid_properties(name, properties):
        return False
    if event_id is not None and (
        not isinstance(event_id, str) or not event_id or len(event_id) > 128
    ):
        return False
    return True


def _remember_once_key(digest: str) -> bool:
    """Remember a hash in this Streamlit session, returning whether it is new."""

    old = _session_get(ONCE_KEYS_KEY, [])
    if not isinstance(old, (list, tuple)):
        old = []
    seen = [item for item in old if isinstance(item, str)]
    if digest in seen:
        return False
    seen.append(digest)
    _session_set(ONCE_KEYS_KEY, seen[-_MAX_ONCE_KEYS:])
    return True


def _next_event_id(name: str, properties: Mapping[str, str]) -> str:
    # A logout can clear Streamlit state without immediately destroying the
    # browser bridge. Fresh ids avoid collisions with its previously sent events.
    return "event:" + uuid.uuid4().hex


def track_event(
    name: str,
    properties: Mapping[str, str] | None = None,
    once_key: Any = None,
) -> bool:
    """Validate and queue one safe event for the next bridge flush.

    ``once_key`` is only represented by a one-way digest in session state and
    in the bridge queue.  It is never passed to Umami.  Invalid events,
    preview instrumentation, and all analytics failures are harmless no-ops.
    """

    try:
        if _preview_is_active() or not _valid_properties(name, properties):
            return False

        event_id: str
        if once_key is not None:
            # JSON primitives are sufficient for a deduplication key.  Reject
            # opaque objects rather than invoking arbitrary ``repr`` methods.
            if not isinstance(once_key, (str, int, float, bool)):
                return False
            once_digest = _hash_once_key(f"{name}:{once_key}")
            if not _remember_once_key(once_digest):
                return False
            event_id = "once:" + once_digest
        else:
            event_id = _next_event_id(name, properties)

        event = {
            "id": event_id,
            "name": name,
            "properties": dict(properties),
        }
        pending = _session_get(QUEUE_KEY, [])
        if not isinstance(pending, list):
            pending = []
        # Keep only records produced by this module.  This also prevents a
        # caller from smuggling arbitrary values into a later JSON payload by
        # pre-populating session state.
        pending = [
            item
            for item in pending
            if isinstance(item, dict)
            and _validated_event(
                item.get("name"), item.get("properties"), item.get("id")
            )
        ]
        if len(pending) >= _MAX_PENDING_EVENTS:
            pending = pending[-(_MAX_PENDING_EVENTS - 1) :]
        pending.append(event)
        if not _session_set(QUEUE_KEY, pending):
            return False
        return True
    except Exception:
        # Analytics is strictly best effort.
        return False


def _load_bridge() -> str:
    return BRIDGE_PATH.read_text(encoding="utf-8")


def _script_json(value: Any) -> str:
    """Encode JSON for a script block, preventing a payload from closing it."""

    return _canonical_json(value).replace("<", "\\u003c")


def _document(bridge: str, pending: list[dict[str, Any]]) -> str:
    encoded_pending = _script_json(pending)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
html, body {{
  margin: 0 !important;
  padding: 0 !important;
  height: 0 !important;
  min-height: 0 !important;
  overflow: hidden !important;
}}
</style></head><body>
<script>window.__APP_ANALYTICS_PENDING__ = {encoded_pending};</script>
<script>
{bridge}
</script>
</body></html>"""


def _pending_events() -> list[dict[str, Any]]:
    pending = _session_get(QUEUE_KEY, [])
    if not isinstance(pending, list):
        return []
    return [
        item
        for item in pending
        if isinstance(item, dict)
        and _validated_event(
            item.get("name"), item.get("properties"), item.get("id")
        )
    ]


def _remove_flushed(flushed: list[dict[str, Any]]) -> None:
    """Clear only events included in a successful mount."""

    flushed_ids = {item["id"] for item in flushed}
    current = _session_get(QUEUE_KEY, [])
    if not isinstance(current, list):
        return
    remaining = [
        item
        for item in current
        if not isinstance(item, dict) or item.get("id") not in flushed_ids
    ]
    _session_set(QUEUE_KEY, remaining)


def flush_analytics() -> bool:
    """Mount the zero-height bridge and clear mounted events on success only."""

    try:
        if _preview_is_active():
            return False
        pending = _pending_events()
        document = _document(_load_bridge(), pending)
        # Streamlit has no delivery callback for components.html.  Reaching
        # this call without an exception is the mount-success signal.
        components.html(document, height=0, scrolling=False)
        _remove_flushed(pending)
        return True
    except Exception:
        # Preserve the queue so a later flush can retry.  No provider details
        # or exception text are allowed to reach the user.
        return False
