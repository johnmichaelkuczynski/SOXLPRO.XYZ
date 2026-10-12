---
name: Overnight market data
description: Preserve chart interactions and distinguish extended-hours monitoring from a continuous overnight feed.
---

Show intraday and extended-hours prices in the existing SOXL chart, not a
separate section above it. Supplementary session prices belong directly below
that chart, replacing the former empty control-panel parking area.

**Why:** The user explicitly rejected the standalone overnight dashboard and
asked for one chart that works during regular and extended sessions.

Refresh prices independently from the full Streamlit page.

**Why:** The user has repeatedly reported losing the prepared historical-chart
view during rerenders. A recurring price refresh must not reset drawings or
recreate the historical chart.

**How to apply:** Keep monitoring updates isolated, with the feed-check time
separate from the observation time. Never substitute regular-session prices
when extended-hours observations are unavailable.

Keep intraday observations out of the daily-history statistical calibration.
Use consistent price adjustment for the historical and intraday trace segments.

**Why:** Mixing five-minute returns with daily returns changes the model's
meaning. The existing feed covers pre/post market, not a continuous
8 p.m.–4 a.m. session; uncovered hours must not be fabricated.

Treat Robinhood's public quote endpoint as best-effort, not a guaranteed
continuous overnight service. Only an actual non-regular trade timestamp can
establish an overnight observation; a response update timestamp cannot.

**Why:** Public endpoint checks supplied after-hours trades, but did not
establish actual 8 p.m.–4 a.m. availability. The user's Robinhood screenshot
expresses a need for true overnight prices, not merely relabeled after-hours.

**How to apply:** Disclose source, observation time, and stale quotes. Keep raw
latest-trade quotes separate from adjusted historical chart bars.