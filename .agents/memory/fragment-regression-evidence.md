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

Real pointer tests must establish that the intended gesture coordinates are
inside the browser viewport, including when the target is in a tall iframe.

**Why:** A valid Playwright bounding box can describe a chart entirely below the
viewport. Sending mouse events to those coordinates silently exercises nothing,
even when the chart initialized and its draw-mode button worked.

**How to apply:** Scroll the drawing surface (not just its toolbar) into view,
re-measure after scrolling, and require both an in-viewport gesture and the
resulting accepted drawing before testing preservation.

Custom component input must not adopt a stale server echo as a new user
selection; explicit resets need a separate reset identity.

**Why:** A component call receives arguments assembled before its returned value
updates Python state. The next render can therefore carry the preceding value
and silently undo a newer keyboard or drag adjustment.

**How to apply:** Treat local input as authoritative after initialization and use
an explicit reset/remount signal for server-driven resets. Check consecutive
drag and keyboard operations, not just the first interaction.
