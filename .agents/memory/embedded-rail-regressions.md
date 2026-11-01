---
name: Embedded rail regressions
description: Testing boundary for floating chart controls and browser zoom.
---

Exercise floating-control reachability in a real Streamlit component host, with
both default and manually sized panels. Keep synthetic price data in this layout
test so market availability cannot gate a layout regression.

**Why:** Standalone markup tests passed while the real host's scroll container
left controls offscreen and parking scrolled the wrong owner. Matching handle
coordinates alone also does not establish that a user can reach a control.

**How to apply:** Include hit testing through both parent and child documents,
actual wheel input, and real browser layout zoom. CSS zoom, device pixel ratio,
and pinch emulation are not substitutes for browser zoom. A test-only Chromium
extension can apply and confirm browser zoom without changing application code.
