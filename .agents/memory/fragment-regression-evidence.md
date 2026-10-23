---
name: Fragment regression evidence
description: Reliable evidence of timed refreshes when cached component HTML is unchanged
---

Observe Streamlit's completed fragment executions, not just iframe messages,
when testing timed refreshes with unchanged market data.

**Why:** A real fragment can run successfully without re-executing identical
cached iframe HTML. Waiting for a new market-update postMessage incorrectly
reported a failed refresh despite a healthy connection.

**How to apply:** Identify the chart fragment from its content in real
Streamlit traffic, then correlate its run identity with successful completion.
Separately check chart state retention. Use isolated servers for restart tests
so the user's preview and background workers remain undisturbed.
