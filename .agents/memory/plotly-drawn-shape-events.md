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

**How to apply:** Preserve a single nearest-line readout, suppress competing
native labels during inspection, and hide the readout away from the lines.