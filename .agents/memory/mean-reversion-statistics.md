---
name: Mean reversion statistics
description: Interpretation of Hurst and half-life comparisons.
---

Use R/S on close-to-close log increments, not raw nonstationary price levels, when interpreting H near 0.5 as random-walk behavior. Show the unbounded raw finite-sample H estimate; clamp only the requested score.

**Why:** Applying ordinary R/S directly to price levels can mislabel a random walk as strongly persistent. Anti-persistence is not proof of price-level stationarity or profitability.

**How to apply:** Preserve that distinction in tooltips and future model integrations. Half-life from price-level change regression is a separate descriptive estimate, not a calibrated buy/sell signal.
