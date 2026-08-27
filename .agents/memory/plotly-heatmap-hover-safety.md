---
name: Plotly heatmap hover safety
description: Avoid a Streamlit/Plotly hover rendering failure caused by mixed-type heatmap customdata.
---

For annotated Plotly heatmaps in Streamlit, prefer a fully preformatted 2D
`hovertext` array with `hovertemplate="%{hovertext}<extra></extra>"` over a
mixed-type, three-dimensional `customdata` array.

**Why:** A mixed numeric/string customdata payload rendered correctly at first,
but hovering produced repeated SVG `<text>` positions with `x="NaN"` in the
browser. Fixing number-format directives alone did not resolve it; removing the
customdata payload did.

**How to apply:** When a heatmap tooltip combines many formatted currency,
percentage, categorical, and optional values, format each tooltip server-side
and pass it as hovertext. Re-test hover interactions while watching fresh
browser-console output.