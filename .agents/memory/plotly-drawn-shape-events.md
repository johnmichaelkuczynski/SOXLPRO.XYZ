---
name: Plotly drawn-shape events
description: Non-obvious Plotly behavior when capturing user-drawn lines, especially on logarithmic axes.
---

Register drawing and relayout handlers through Plotly's event API after the plot has initialized; DOM event listeners can leave visible shapes uncaptured. Treat drawn-shape Y coordinates on logarithmic axes as actual data values rather than logarithmic exponents.

**Why:** A line could appear on screen while application state remained empty, and an additional exponentiation would turn valid dollar coordinates into unusable values.

**How to apply:** When features depend on user-drawn Plotly shapes, bind the relayout handler after the initial plot promise resolves and verify both the visible shape and the synchronized application state.

Treat drawing-model restoration and visible drawing removal as separate Undo
checks. Preserve the viewport without preserving obsolete native drawing edits.

**Why:** Undo restored an empty model while Plotly retained a native line shape
under a stable viewport revision. A model-only assertion falsely passed.

**How to apply:** Check native/SVG shapes and application-owned channel traces
as well as the restored model. Keep editable-shape revision separate from
viewport revision when consuming temporary native shapes into trace data.

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

Each projection comparison card must match its corresponding trendline color.

**Why:** The user explicitly requires matching colors to identify each line's readout.

**How to apply:** Preserve the match for every line's card within the shared
same-date comparison, including automatic and explicitly selected lines.

Keep projection inspection available while period-selection mode is enabled;
hide it only during an active selection drag.

**Why:** Users expect hovering a trendline to show its price without having to
leave the analysis mode they previously enabled.

**How to apply:** Distinguish an enabled mode from an active gesture when deciding
whether to suppress readouts, and check that readouts return on mouse release.

Do not rely solely on native DOM double-click events for chart shortcuts.
Recognize real pointer taps without counting pan drags, include sibling chart
overlays, and disable Plotly's conflicting double-click autoscale behavior.

**Why:** The user reported that the horizontal guide was unavailable despite a
native double-click listener passing a synthetic DOM-event check.

**How to apply:** Regression checks must exercise pointer down/up sequences
without dispatching a native double-click, and ensure one gesture creates only
one undo entry when both event paths fire.