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