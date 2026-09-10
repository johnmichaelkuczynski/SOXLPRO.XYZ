---
name: Chart interaction default
description: Initial interaction mode for the historical SOXL chart.
---

**Rule:** Load the chart in pan/navigation mode with drawing turned off. The
Draw Line control should be inactive and explicitly enable drawing when pressed.

**Why:** Users normally reposition the chart before drawing. Starting in drawing
mode creates accidental lines that they must erase.

**How to apply:** On every fresh chart load, a chart drag should pan without
creating a line. Drawing begins only after the user presses Draw Line, and Stop
Drawing returns the chart to pan mode.

**Viewport rule:** Enabling drawing and completing any new line must preserve
the user's exact pan, zoom, chart dimensions, scroll position, scale, and panel
position. Erase, extend, undo, and double-click erase must preserve them too.

**Why:** Automatically fitting prices when drawing starts, or resetting axis
ranges when a new line triggers a rerender, destroys the view the user prepared
before drawing.

**Implementation constraint:** Do not rely only on Plotly `uirevision` for line
operations. Capture the live axis ranges and chart scroll offsets before a
rerender and put those exact values into the replacement layout. Do not
reposition the controls panel as a side effect of updating the line list.