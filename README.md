# 📈 SOXL ANALYSIS PLATFORM

**Quantitative Analysis, Probability Engine, and AI Strategy Builder for SOXL (3× Semiconductor ETF)**

---

## 🧩 Overview

The SOXL Analysis Platform is a single-page quantitative research tool for SOXL (Direxion Daily Semiconductor Bull 3X Shares). It combines interactive log-scale charting, historical probability modeling, benchmark-anchored deviation analysis, vol-surface diagnostics, a full call-sleeve backtest engine, and an AI-powered strategy builder driven by Anthropic Claude.

Unlike generic charting dashboards that stop at price plots, this platform is built around an operating principle: every analysis is honest, every metric is auditable, and the engine never refuses to return a result — even on a two-data-point window. If you ask for a backtest, you get a backtest. If you ask for a probability, you get the actual historical frequency with its sample size attached. No padding, no hand-waving, no synthetic placeholders.

---

## 👥 Who It's For

- **Active traders and SOXL holders** -- need to size positions, time entries, and understand the asymmetric risk profile of a leveraged ETF
- **Options traders** -- need realistic premium-based strategy backtests with honest Black-Scholes mark-to-market and roll mechanics
- **Quantitative researchers** -- need to test historical mean-reversion, dislocation, and vol-regime hypotheses against real adjusted price data
- **Portfolio managers** -- need risk-adjusted metrics (Sharpe, Sortino, Calmar, capital-at-risk) to compare strategies on a level playing field
- **Anyone running a semiconductor thesis** -- who wants to know the actual historical probability of a move, not a vibes-based estimate

---

## ⚙️ Core Capabilities

- **Interactive Log-Scale Price Chart** -- Full SOXL price history from 2010 to present, rendered in log scale with x-axis extending 5 years into the future. Click-and-drag trend-line drawing via a custom Streamlit component; lines auto-extend forward (dashed projection) and backward (dashed historical).

- **Probability Engine** -- Historical probability of any price move (magnitude × time horizon) computed from a configurable rolling window of actual SOXL returns. "Benchmark History" mode predicts SOXL behavior from the recent 30-day move of a benchmark (QQQ, TLT, XLU, VIX) and its historical analogues. Sample size is always shown — no probability without its denominator.

- **Period Analysis / Backtest** -- Select any window on the chart. "SOXL Patterns" mode uses SOXL's own rolling returns. "Benchmark-Based" mode builds the conditional relationship between a benchmark's 30-day move and SOXL's subsequent return during the selected period, then compares predictions to actual post-period outcomes with the per-horizon analogue count.

- **Benchmark Overlays** -- QQQ (orange), TQQQ (purple), TLT (teal), XLU (red), VIX (gold dotted) — all rendered on the same log-scale y-axis for direct relative-strength reading.

- **Short Interest** -- FINRA daily short-volume chart for the last 12 months, fetched in parallel HTTP for fast load.

- **Vol Surface (limited)** -- BUY/SELL discrepancy view on the available SOXL options chain, highlighting where market-maker skew suggests directional positioning.

- **SOXL-QQQ Dislocation** -- Continuous deviation panel: SOXL_norm − QQQ_norm with rolling baseline, used as the core sizing signal for the allocation engine.

- **Strategy Builder (AI)** -- Conversational interface powered by Anthropic Claude via Replit AI Integrations. User describes their portfolio, available cash, and risk tolerance; Claude generates a personalized SOXL entry strategy with a tranched buy ladder, operating rules, and the statistical basis — rendered as a styled HTML strategy document.

- **Backtest — Allocation Engine (DEFAULT)** -- 20% call-sleeve / 80% cash strategy. Long SOXL calls (default 45-DTE ATM, rolled at 10 DTE) sized continuously by deviation = SOXL_norm − QQQ_norm via a tanh sizing function. Hard floor 2% / hard ceiling 98% inside the sleeve. QQQ bear-regime filter scales sleeve fill (floor still wins). Asymmetric resize: sells down freely (locks in profits / reduces exposure), refills only at roll events — honors both "continuous rebalancing" and "limited downside = premium". Calls priced via Black-Scholes (math.erf, no scipy) with trailing realized vol. Always returns a result for any window (even 2 data points).

- **Risk-Adjusted Metrics Panel** -- Every backtest run reports Total Return, CAGR, annualized Volatility, Max Drawdown, Sharpe, Sortino, Calmar, Capital at Risk, and Return per Unit of At-Risk Capital — for the strategy AND for SOXL B&H and QQQ B&H baselines on the same axis. Capital-efficiency callout compares return-per-at-risk-dollar across all three.

- **Custom Strategy Builder** -- Compose your own indicator/operator combinations against the price history, with the same risk-metric output panel as the default engine.

- **Always-On Data Layer** -- Equity history up to ~20 years via EODHD, options snapshots and history via Polygon, all responses cached 24h. No external rate-limit surprises during a research session.

---

## 🚀 What Makes It Different

- **It never refuses to compute** -- The allocation engine returns a valid recommendation for any window, including degenerate 1- or 2-bar inputs. The risk-metrics table always renders, with zero-values when the sample is too small to be meaningful, never a "please pick a longer window" dialog.

- **Honest options modeling, no fake leverage** -- Calls are priced with plain Black-Scholes using trailing realized vol of SOXL. No vol-surface fitting, no Heston, no IV-smile fairy dust — and critically, no infinite refill of decaying premium. The asymmetric resize rule (sell down freely, refill only at rolls) cleanly caps loss at the premium paid per cycle, which is the actual behavior of a real long-call sleeve.

- **Capital efficiency is a first-class metric** -- Every backtest shows Return per At-Risk Capital, not just total return. The strategy uses 20% of notional at risk vs SOXL B&H's 100%, and the platform reports both raw return AND return-per-risked-dollar so you can see which strategy is actually working harder.

- **Drawdown protection is verifiable** -- In a SOXL −70% stress scenario, the default engine demonstrates capital protection in numbers, not in marketing copy. You can re-run the backtest yourself on any window and see the Max DD / Sortino / Calmar gap vs buy-and-hold.

- **Probability with sample size** -- Every probability output ships with the count of historical analogues that backs it. A "65% chance of a 10% drop in 30 days" with n=4 is shown as exactly that, so the user can judge the statistical weight before acting.

- **No look-ahead leakage** -- The allocation signal is explicitly lagged one bar before being applied to returns. Realized-vol pricing uses only data up to today for today's mark-to-market. The engine is auditable in `backtest_engine.py` if you want to verify.

- **One-click report export** -- After any backtest, download a complete TXT / CSV / Word / PDF report with parameters, methodology, metrics, and date range. Methodology text describes the actual implementation, not a glossy version of it.

- **AI strategy builder grounded in real data** -- Claude doesn't generate strategy in a vacuum. The conversation includes the full computed probability tables and recent deviation context, so the generated entry ladder is anchored to actual historical frequencies, not LLM intuition.

- **No external billing surprises** -- Anthropic Claude runs via Replit AI Integrations (no API key, uses Replit credits). EODHD + Polygon for data, both cached locally.

---

## 🛠️ Tech Stack

- **Python 3.11** with **Streamlit** for the single-page UI
- **Plotly** for interactive charting (via a custom HTML/JS component for drag-to-draw trend lines)
- **EODHD** (equity history up to 20y) + **Polygon** (options history, capped at 2y)
- **yfinance** for supplementary intraday/snapshot quotes
- **Anthropic Claude** via Replit AI Integrations — no key needed, uses Replit credits
- **dateutil** for trading-day math
- **Black-Scholes pricing** implemented natively with `math.erf` — zero scipy dependency

---

## 📂 Project Structure

- `app.py` -- Main Streamlit entry; tab layout (Chart & Probabilities, Backtest, Strategy Builder)
- `backtest_engine.py` -- All simulation math: `simulate_call_sleeve_engine`, `compute_risk_metrics`, `_bs_call_price`, deviation engine
- `backtest_ui.py` -- Backtest tab UI: allocation engine, period analysis, probability engine, vol regime, dislocation, custom strategy, vol surface
- `strategy_builder.py` -- AI strategy generation: Anthropic client, probability computations, strategy JSON parsing, styled HTML rendering
- `data_providers.py` -- EODHD / Polygon / yfinance wrappers with 24h caching
- `vol_surface.py` -- Options-chain BUY/SELL discrepancy analytics
- `dislocation.py` -- SOXL-QQQ continuous deviation panel
- `custom_strategy.py` -- User-composable indicator/operator strategy builder
- `components/chart_draw/index.html` -- Custom Streamlit component for the drag-to-draw chart
- `.streamlit/config.toml` -- Streamlit server configuration

---

## ▶️ Running

```bash
streamlit run app.py --server.port 5000
```

Then open the preview at port 5000. The default tab loads the SOXL log-scale chart; the Backtest tab opens directly on the Allocation Engine (the default strategy).
