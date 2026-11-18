---
name: Projection hit probabilities
description: Approved presentation and interpretation for probability estimates on future SOXL trend-line points.
---

**Rule:** When a user hovers over a future trend-line point, show the projected
date, projected SOXL price, and “Probability of hitting this by or before this
date: XX.X%” together. Identify the percentage as a historical-model estimate.

**Why:** The user explicitly confirmed this presentation was perfect. “By or
before” means the chance of reaching the target at least once before the
deadline, not merely closing at that price on the displayed date.

**How to apply:** Preserve the exact probability interpretation and keep the
estimate visibly qualified whenever future projection hover behavior changes.

Inspecting one trendline should compare every existing valid trendline at the
same date, each with its own projected price, by-or-before hit probability,
name, and matching line color. Include manually drawn lines, not just the three
automatic channels; do not create missing lines for the comparison.

**Why:** The user explicitly requested instant same-date comparisons instead
of inspecting the lower, median, and upper lines separately. The three channels
were an example, not a limit on which existing trendlines to compare.

**How to apply:** Keep one shared-date comparison readout. Explicit selection
can choose the inspected line but must not filter out the other comparisons.
Order the cards from highest projected price to lowest at that date, matching
the trendlines' visual top-to-bottom order rather than their creation order.

**Why:** The user explicitly corrected the reversed comparison order and wants
the top line's price/probability first, the middle next, and the bottom last.

For targets below the starting price, “hitting” means a future downward touch,
not simply being at or above the target already.

**Why:** The user flagged the lower green line always reporting 100%. Treating
all lower barriers as already reached contradicts the intended projection.

**How to apply:** Use directional first-passage probabilities for both upside
and downside barriers. Never force lower targets to certainty. These are
historically fitted model estimates, not empirically verified success rates.

Historical tests must refit channels using only data available at each forecast
date and train probability adjustments only on outcomes already known then.
Do not backtest today's full-history channels as if they were past forecasts.

**Why:** The user explicitly raised lookahead contamination and requested a
walk-forward comparison of area and channel projections against a plain baseline.

**How to apply:** Keep exploratory area rules distinct from discretionary boxes
and from the frozen daily-signal holdout. Report negative results and sampling
limitations; do not silently replace live popup probabilities with a model
selected after inspecting the historical results.