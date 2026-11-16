---
name: Price-axis readability
description: Readable price labels and fitting behavior for the SOXL comparison chart.
---

Fit both axes to the selected date window. Fit the Y-axis only to finite,
positive prices actually plotted in that window, including visible benchmark
overlays. Exclude all drawn/channel projections and hidden series from fitting.
Use about 5–10% padding and 5–8 readable dollar labels without scientific notation.

**Why:** The user explicitly requested these bounds after repeated astronomical
axis limits compressed the actual historical series into a tiny segment.

Price fitting must use only visible series. Hidden benchmark histories must
never compress the SOXL-only chart. Keep a direct price-fit action above the
graph without deleting drawings or resetting the chosen time window.

**Why:** Invisible comparison data can have a very different normalized range;
including it makes the displayed SOXL series appear needlessly small.

Keep the normal chart compact. Show historical dates by default; future dates
must be an explicit choice, not automatic empty space. Reset View must restore
the current selected date window and its fitted prices without deleting lines.

**Why:** The user explicitly asked to prune the huge, mostly empty chart instead
of spending time navigating back to actual prices.

Mouse-wheel movement over the plot must scroll the page, not zoom the price
axis. Keep a visible one-action route below the chart.

**Why:** The user could not leave the chart without finding the outer scrollbar;
ordinary scrolling instead drove the logarithmic axis to astronomical prices.

**How to apply:** Forward ordinary vertical wheel events to the real Streamlit
scroll owner, preserve browser zoom/horizontal gestures, and leave chart zoom
available through explicit controls. Queue range corrections during active
relayouts so rapid gestures cannot bypass the price bounds.

Do not reintroduce Chart incline, its slider, or its explanatory commentary.

**Why:** The user explicitly ordered their removal while asking for real axis
repair rather than merely different tick formatting.

Interpret Plotly timezone-less date/time range strings as UTC chart coordinates.
**Why:** Browser-local parsing changes them in non-UTC timezones and can make
the range-repair listener repeatedly relayout an already-correct date range.
