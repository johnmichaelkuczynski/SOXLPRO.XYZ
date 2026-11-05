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

Size embedded frames from intrinsic document-flow content, not their current viewport or floating-control overflow. Keep docked controls bounded by the plot.

**Why:** Feeding the current `scrollHeight` plus padding back into iframe sizing can increase the frame with every update. A floating panel that follows parent scrolling beyond the plot then makes empty space look like a missing graph.

**How to apply:** Check repeated resizing in an oversized iframe and scroll between the plot and lower-page controls. The reported height must remain stable; the docked panel must not extend the document to follow an offscreen chart.
