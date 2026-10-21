---
name: Daily signal validation
description: User's trading horizon and strict frozen-holdout policy for short-term buy signals.
---

The user says paying users mostly trade one-month horizons; the composite
historical-range indicator is a separate long-term signal.

**Why:** Their supplied analysis showed that Possible Buy underperformed the
one-month baseline despite strong long-horizon ordering.

Freeze short-term rules using 2010–2018 only, then evaluate 2019–2026 once.
Do not keep retuning against the holdout. If the frozen BUY does not achieve
at least +10 percentage points versus baseline with 30 non-overlapping
observations, show NO EDGE every day.

**Why:** Explicit user acceptance policy; failure must be disclosed rather than
optimized away. A high percentage with a tiny sample is not sufficient.

**How to apply:** Preserve the frozen rule and evaluation cohort. Treat any
future study as a separately identified experiment rather than overwriting the
holdout or presenting a retrospectively gated policy as real-time recommendations.
Keep the existing common-calendar non-overlap and next-session-close conventions.
