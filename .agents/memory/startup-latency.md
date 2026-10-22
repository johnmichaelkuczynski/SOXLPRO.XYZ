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
