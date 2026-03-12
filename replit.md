# SOXL Analysis Web App

## Overview
A single-page Streamlit web application for analyzing SOXL (Direxion Daily Semiconductor Bull 3X Shares) historical price data with interactive charting, probability analysis, and AI-powered strategy building.

## Features
- **SOXL Price Chart**: Interactive Plotly chart in log scale showing complete price history from 2010 to present, with x-axis extending 5 years into the future
- **Trend Line Drawing**: Click-and-drag drawing on the chart via custom Streamlit component; lines auto-extend into the future (dashed) and backward (dashed)
- **Probability Engine**: Calculate historical probability of price moves of a given magnitude over a given time horizon, using a configurable historical data window. Includes "Benchmark History" mode that predicts SOXL based on a benchmark's recent 30-day behavior and historical analogues.
- **Period Analysis / Backtest**: Select a period on the chart to analyze. "SOXL Patterns" mode uses SOXL's own rolling returns; "Benchmark-Based" mode builds the relationship between a benchmark's 30-day moves and SOXL's subsequent returns during the selected period, then compares predictions to actual post-period outcomes. Supports QQQ, TLT, XLU, VIX as benchmarks. Shows sample size (analogues) per horizon.
- **Benchmark Overlays**: QQQ (orange), TQQQ (purple), TLT (teal), XLU (red), VIX (gold dotted) — all on the same log-scale y-axis.
- **Short Interest**: FINRA daily short volume chart (last 12 months) with parallel HTTP fetching.
- **Strategy Builder**: AI-powered conversational strategy builder using Anthropic Claude (via Replit AI Integrations). User describes their portfolio, cash, risk tolerance; the AI generates a personalized SOXL entry strategy with tranched buy ladder, operating rules, and statistical basis — rendered as a styled strategy document.

## Tech Stack
- Python 3.11 / Streamlit
- yfinance for market data
- Plotly for interactive charting (via custom HTML component)
- Anthropic Claude (Replit AI Integrations — no API key needed, uses Replit credits)
- dateutil for date math

## Structure
- `app.py` — Main application with tabs (Chart & Probabilities, Strategy Builder)
- `strategy_builder.py` — AI strategy generation: Anthropic client, probability computations, strategy parsing, HTML rendering
- `components/chart_draw/index.html` — Custom Streamlit component for interactive chart with drag-to-draw trend lines
- `.streamlit/config.toml` — Streamlit server configuration

## Key Implementation Details
- Chart component uses pixel-to-data coordinate conversion for log-scale y-axis
- Drawing uses transparent overlay div to capture mouse events without Plotly interference
- Strategy builder sends full conversation history + computed probability tables to Claude
- Strategy JSON is parsed from Claude's response and rendered as styled HTML tables
- Replit AI Integrations env vars: `AI_INTEGRATIONS_ANTHROPIC_BASE_URL`, `AI_INTEGRATIONS_ANTHROPIC_API_KEY`

## Running
```bash
streamlit run app.py --server.port 5000
```
