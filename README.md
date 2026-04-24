# SOXL Analysis App

Streamlit + Plotly app for SOXL analysis: log-scale price chart with drag-to-draw trend lines, probability engine, AI strategy builder (Anthropic Claude), period analysis with benchmark overlays, options IV surface with anomaly-based BUY/SELL recommendations, SOXL–QQQ relative dislocation surface, and a full backtest module.

## Run

```bash
streamlit run app.py --server.port 5000
```

## Required environment secrets

| Secret | Purpose | How to obtain |
|---|---|---|
| `ANTHROPIC_API_KEY` | Powers the Strategy Builder tab. | https://console.anthropic.com |
| `EODHD_API_KEY` | Equity price history (16 years of SOXL/QQQ daily OHLC) for the Backtest tab. | https://eodhd.com |
| `POLYGON_API_KEY` | Options chain snapshots and per-contract historical aggregates (4 years) for the Vol Surface backtest. | https://polygon.io |
| `SESSION_SECRET` | Streamlit session state. | Auto-generated. |

API responses for both EODHD and Polygon are cached locally for 24 hours to avoid rate-limit issues during iterative use.

## Tabs

- **📊 Chart & Probabilities** — log-scale chart, drag-to-draw, period analysis, probability engine, benchmark overlays, short-interest panel.
- **🌊 Vol Surface** — live SOXL options IV surface (calls and puts as independent surfaces), per-expiry cubic-spline fit in (log-moneyness, time) space, BUY/SELL signals when market IV diverges from the fitted surface.
- **⚖️ SOXL–QQQ Dislocation** — rolling-beta residual z-scores, mean-reversion lookup table.
- **🎯 Strategy Builder** — Claude-generated personalized SOXL entry/exit strategy.
- **🔬 Backtest** — sub-tab per analytical function:
  - Period Analysis (drawdown-trigger mean-reversion)
  - Probability Engine (calibration plot + Brier score)
  - Vol Regime (long when realized vol is in the low percentile band)
  - SOXL–QQQ Dislocation (z-score entry/exit)
  - Strategy Builder (level-based, walk-forward 70/30 split)
  - Vol Surface signals (limited — 4y options history)

  Each backtest reports CAGR, max drawdown, Sharpe, hit rate, avg win/loss, trade count; plots equity curves vs. SOXL buy-and-hold, QQQ buy-and-hold, and a random-entry baseline (overfitting check). The Probability Engine backtest is a forecast-accuracy test (calibration + Brier) rather than a P&L test.

## Modules

- `app.py` — main Streamlit entrypoint.
- `vol_surface.py` — IV surface, fit, anomaly detection.
- `dislocation.py` — SOXL–QQQ residual z-scores.
- `strategy_builder.py` — Anthropic Claude integration.
- `data_providers.py` — EODHD and Polygon clients with 24h cache.
- `backtest_engine.py` — equity-curve, stats, calibration, random-entry baseline, chart helpers.
- `backtest_ui.py` — per-function backtest sub-tabs.
- `components/chart_draw/` — custom Streamlit drag-to-draw chart component.
