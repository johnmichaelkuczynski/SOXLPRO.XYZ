---
name: Startup latency
description: Saved-data startup requirement and gateway compatibility pitfalls.
---

The user requires a page with the last database-backed market snapshot and
signals within two seconds of process boot; market recomputation belongs in a
background worker, not a request-triggered cache miss.

**Why:** The published app could take about a minute after idle. Even importing
Streamlit delayed port binding, independently of provider downloads.

**How to apply:** Keep the initial listener free of Streamlit/scientific imports.
Measure port readiness, saved-data rendering and full interactive readiness
separately. Do not describe a saved bootstrap page measurement as full chart
readiness or as a production idle test. An absent/unreachable database must
produce an explicit unavailable state, not fabricated saved data.

Preserve backend MIME types by replacement, not append, and never call
Tornado finish with a body argument for 204/304 responses.

**Why:** Duplicate Content-Type made browsers reject JavaScript modules, and
even an empty bytes body on a 304 caused conditional reloads to return 503.

**How to apply:** Keep proxy regression coverage for asset MIME, multiple
Set-Cookie headers and browser cache revalidation, as well as WebSocket handoff.

Retain validated saved state when database reads time out or overlap. Keep
successful late responses, and automatically retry when no saved state exists.
Show retained-data warnings without changing observation timestamps.

**Why:** A bounded read previously returned nothing on contention and discarded
late results, leaving the app stopped even though valid database data existed.
Never claim a background worker is running merely because a read failed.

**How to apply:** Exercise busy reads, timeouts, late completion, and recovery,
not just the successful startup path. After code changes, check a full timed
fragment refresh cycle to catch old functions retained by Streamlit sessions.

Test already-open browser tabs across backend restarts, not only fresh pages.
Keep recovery UI outside Streamlit's React root and preserve bootstrap requests
while the backend starts.

**Why:** Fresh sessions rendered successfully while the user's existing preview
remained blank with delta-path errors and disconnected-session messages.

**How to apply:** A fresh screenshot does not prove an existing tab recovered.
Distinguish server readiness from that tab's state and give an explicit fresh
session link when its previously loaded frontend cannot receive the fix.

Gateway shortcuts must preserve Streamlit's XSRF cookie bootstrap, even for GET
pages and health responses.

**Why:** Streamlit silently ignores an otherwise valid login cookie when the
WebSocket's XSRF token is missing. A custom HTML root plus an intercepted health
response left real browsers without the token, making completed Google logins
appear signed out.

**How to apply:** Retain the backend health response once ready, and issue the
framework's XSRF cookie from any custom entry document. Verify token presence in
a fresh browser and validation by Streamlit; never disable XSRF as a workaround.
