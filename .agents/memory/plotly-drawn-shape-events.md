---
name: Plotly drawn-shape events
description: Non-obvious Plotly behavior when capturing user-drawn lines, especially on logarithmic axes.
---

Register drawing and relayout handlers through Plotly's event API after the plot has initialized; DOM event listeners can leave visible shapes uncaptured. Treat drawn-shape Y coordinates on logarithmic axes as actual data values rather than logarithmic exponents.

**Why:** A line could appear on screen while application state remained empty, and an additional exponentiation would turn valid dollar coordinates into unusable values.

**How to apply:** When features depend on user-drawn Plotly shapes, bind the relayout handler after the initial plot promise resolves and verify both the visible shape and the synchronized application state.

Use one projection-tooltip owner, not simultaneous Plotly and custom readouts.

**Why:** The user could not read the lower trendline's future projection because
another trendline's popup covered it. Independent hover hit-testing can select
different lines at the same pointer position.

**How to apply:** Provide explicit line selection as well as nearest-line
inspection; calculate projections at the pointer date rather than relying only
on sampled Plotly marker hits. The user repeatedly reported that hover-only
fixes remained unusable. Keep native hover as a fallback but suppress it only
while the continuous readout is visible. Verify actual automatic channel lines
in a real browser, including explicit lower-line selection while the pointer is
near a different line. Clamp popups to the visible parent viewport, not merely
the tall chart iframe. Floating controls can intercept pointer events over
future chart points; selection must allow reading the chosen line elsewhere.