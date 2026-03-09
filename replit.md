# SOXL Analysis Web App

## Overview
A single-page Streamlit web application for analyzing SOXL (Direxion Daily Semiconductor Bull 3X Shares) historical price data with interactive charting and probability analysis.

## Features
- **SOXL Price Chart**: Interactive Plotly chart in log scale showing complete price history from 2010 to present, with x-axis extending 5 years into the future
- **Trend Line Drawing**: Users can draw trend lines by selecting two dates/prices; lines auto-extend into the future (dashed) and backward (dashed) with the same slope
- **Probability Engine**: Calculate historical probability of price moves of a given magnitude over a given time horizon, using a configurable historical data window

## Tech Stack
- Python 3.11 / Streamlit
- yfinance for market data
- Plotly for interactive charting
- dateutil for date math

## Structure
- `app.py` — Main application (single file)
- `.streamlit/config.toml` — Streamlit server configuration

## Running
```bash
streamlit run app.py --server.port 5000
```
