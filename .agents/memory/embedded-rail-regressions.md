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

Free-floating panels must also fit the visible parent viewport, with readable,
internally scrollable controls and a reachable drag header.

**Why:** The user could not reach date inputs when a freely moved panel extended
below the screen; enlarging the page must not be necessary to use it.

**How to apply:** Apply viewport height limits to free positioning. A docked
console in its own reserved gutter may use full height without covering the
plot; preserve intentional below-chart parking separately.

Do not choose responsive docking only from the iframe's initial script-time
width. Re-evaluate after Plotly initializes and when the host resizes.

**Why:** A Streamlit iframe can start narrow and expand before its final layout,
leaving a desktop console wrongly parked below the plot with an unused gutter.

Free dragging must permit placing the console above the entire embedded chart
section, into the surrounding main page—not just into the component's own
benchmark/action area. The plot boundary applies only to side docking.

**Why:** The user again reported the console stuck inside the graph after the
earlier within-component movement change. An iframe clips its contents regardless
of their stacking priority; removing a plot-top clamp alone is insufficient.

**How to apply:** Prove a real drag across the iframe's upper boundary in the
actual Streamlit host. Preserve the existing drawing model and control callbacks
when changing the console's hosting document; pointer events must follow that
document. Isolated diagnostic frames must never promote controls onto the user's
main page.

Free dragging includes the app-header region. Holding the pointer at a viewport
edge must scroll the actual Streamlit page so the same drag can reach sections
above or below the currently visible chart. Stop scrolling on release, cancel,
lost capture, or disposal; isolated diagnostics must not scroll the user page.

**Why:** The user repeated that the panel must move anywhere in the app, not
merely across the graph or within one visible screen.

**How to apply:** Schedule drag animation on the controls' owning window. The
chart iframe can scroll out of view while its promoted controls remain visible;
depending on the child frame's animation clock can stall the visible interaction.
Keep minimum readable panel height inside the viewport at its lower edge.
