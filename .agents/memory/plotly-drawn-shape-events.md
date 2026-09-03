---
name: Plotly drawn-shape events
description: Non-obvious Plotly behavior when capturing user-drawn lines, especially on logarithmic axes.
---

Register drawing and relayout handlers through Plotly's event API after the plot has initialized; DOM event listeners can leave visible shapes uncaptured. Treat drawn-shape Y coordinates on logarithmic axes as actual data values rather than logarithmic exponents.

**Why:** A line could appear on screen while application state remained empty, and an additional exponentiation would turn valid dollar coordinates into unusable values.

**How to apply:** When features depend on user-drawn Plotly shapes, bind the relayout handler after the initial plot promise resolves and verify both the visible shape and the synchronized application state.