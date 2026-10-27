---
name: Hypothetical entry price slider
description: User-confirmed meaning of the SOXL price scenario slider.
---

The user confirmed a separate $1–$500 draggable slider starting at the latest SOXL price, preserving the existing daily indicator. It asks what happens after entering at the chosen hypothetical price, not the odds of reaching that price. Show forward one-, six-, and twelve-month outcomes, upside probability, dollar/percent changes, and downside ranges.

**Why:** The user explicitly confirmed this interpretation before requesting implementation. Simply rescaling a constant percentage-return forecast would not answer their price-dependent question.

**How to apply:** Keep model estimates distinct from validated next-trade probabilities and from the frozen short-term NO EDGE rule. User explicitly requires extrapolated estimates throughout $1–$500, not missing probabilities at sparse prices. Label extrapolation and uncertainty; do not manufacture numerical differences or confidence.

The probability must appear directly above the slider handle and update during dragging, not merely in a results section after release.

**Why:** The user rejected the separate below-slider readout and explicitly required above-cursor feedback.
