---
name: Overnight market data
description: Preserve chart interactions and distinguish extended-hours monitoring from a continuous overnight feed.
---

Refresh extended-hours prices independently from the full Streamlit page.

**Why:** The user has repeatedly reported losing the prepared historical-chart
view during rerenders. A recurring price refresh must not reset drawings or
recreate the historical chart.

**How to apply:** Keep monitoring updates isolated, with the feed-check time
separate from the observation time. Never substitute regular-session prices
when extended-hours observations are unavailable.

Use provider session boundaries and unadjusted regular closes for the overnight
baseline; evening and next-morning observations belong to the same close.

**Why:** Calendar-day changes and early exchange closes make fixed-date or
fixed-hour assumptions misleading. The existing feed covers pre/post market,
not a continuous 8 p.m.–4 a.m. session.