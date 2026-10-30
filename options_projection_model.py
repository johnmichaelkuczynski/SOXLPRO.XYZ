"""Conditional scenarios, NOT calibrated option-profit predictions.

Uses the chart's historical log-return drift/volatility, then European
Black–Scholes repricing. American exercise, jumps, costs and IV dynamics are
not estimated. IV scenarios are explicit sensitivity assumptions.
"""
from datetime import datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.special import ndtr


def price(spot, strike, years, iv, rate, dividend, kind):
    spot = np.asarray(spot, dtype=float)
    intrinsic = np.maximum(spot - strike if kind == "call" else strike - spot, 0)
    if years <= 0:
        return intrinsic
    root = iv * np.sqrt(years)
    d1 = (np.log(spot / strike) + (rate - dividend + iv * iv / 2) * years) / root
    d2 = d1 - root
    if kind == "call":
        value = spot * np.exp(-dividend * years) * ndtr(d1) - strike * np.exp(-rate * years) * ndtr(d2)
    else:
        value = strike * np.exp(-rate * years) * ndtr(-d2) - spot * np.exp(-dividend * years) * ndtr(-d1)
    return np.maximum(value, 0)


def project(history, contract, premium, horizon_date, contracts=1, iv_factor=1.,
            rate=.04, dividend=0., now=None, samples=4000, return_paths=False,
            drift_override=None):
    now = now or datetime.now(ZoneInfo("America/New_York"))
    if now.tzinfo is None:
        raise ValueError("Projection time must include a timezone.")
    expiration = pd.Timestamp(contract["expiration"]).date()
    end = datetime.combine(expiration, time(16), ZoneInfo("America/New_York"))
    if end <= now or (end-now).days > 1100:
        raise ValueError("Choose an unexpired contract within three years.")
    if not now.date() < horizon_date <= expiration:
        raise ValueError("Selling date must be after today and no later than expiration.")
    if contract.get("adjusted") or contract.get("multiplier") != 100:
        raise ValueError("Adjusted/nonstandard contracts are not supported.")
    if contract.get("type") not in ("call", "put"):
        raise ValueError("Contract must be a call or put.")
    spot, strike, iv = (float(contract.get(k) or 0) for k in ("spot", "strike", "iv"))
    if not all(np.isfinite(x) and x > 0 for x in (spot, strike, iv, premium, iv_factor)):
        raise ValueError("Positive spot, strike, implied volatility and purchase price are required.")
    if not np.isfinite(rate) or not np.isfinite(dividend) or not 1 <= contracts <= 10000:
        raise ValueError("Invalid position size or pricing assumptions.")
    for field in ("quote_time", "spot_time"):
        if not contract.get(field):
            raise ValueError("Both option and underlying quote timestamps are required.")
        age = (pd.Timestamp(now) - pd.Timestamp(contract[field])).total_seconds()
        if age < -300 or age > 4 * 86400:
            raise ValueError("Quotes are too old for a projection. Refresh the chain.")
    # Historical studies pass only point-in-time observations (including their
    # availability cutoff); the interactive chart also supports undated history.
    close = pd.to_numeric(history["Close"], errors="coerce").dropna()
    close = close[close > 0]
    returns = np.diff(np.log(close.to_numpy()))
    if len(returns) < 252 or not np.all(np.isfinite(returns)):
        raise ValueError("At least one year of valid SOXL history is required.")
    drift, sigma = float(returns.mean() * 252), float(returns.std(ddof=1) * np.sqrt(252))
    if drift_override is not None:
        if not np.isfinite(drift_override):
            raise ValueError("Invalid drift override.")
        drift = float(drift_override)
    # Calendar-day resolution; weekends have model time, not executable quotes.
    dates = [now]
    for day in pd.date_range(now.date(), expiration, freq="D"):
        dt = datetime.combine(day.date(), time(16), ZoneInfo("America/New_York"))
        if dt > now:
            dates.append(dt)
    years = np.array([(d-now).total_seconds()/ (365.25*86400) for d in dates])
    rng = np.random.default_rng(2026)
    stocks = np.full(samples, spot)
    values = np.empty((samples, len(dates)))
    for j, elapsed in enumerate(years):
        if j:
            dt = elapsed - years[j-1]
            stocks *= np.exp(drift*dt + sigma*np.sqrt(dt)*rng.standard_normal(samples))
        # Volatility sensitivity transitions from observed IV to the scenario.
        scenario_iv = iv * (1 + (iv_factor - 1) * elapsed/years[-1])
        values[:, j] = price(stocks, strike, years[-1]-elapsed,
                             scenario_iv, rate, dividend, contract["type"])
    index = next(j for j, d in enumerate(dates) if d.date() == horizon_date)
    position_pl = (values[:, index] - premium) * 100 * contracts
    result = {
        "dates": dates, "quantiles": np.quantile(values, [.05,.25,.5,.75,.95], axis=0),
        "profit_probability": (values > premium).mean(axis=0),
        "multiplier": 100, "horizon_index": index,
        "horizon_profit_quantiles": np.quantile(position_pl, [.05,.25,.5,.75,.95]),
        "horizon_profit_probability": float((position_pl > 0).mean()),
        "path_high95": float(np.quantile(values[:, :index+1].max(axis=1), .95)),
        "path_low05": float(np.quantile(values[:, :index+1].min(axis=1), .05)),
        "samples": samples,
    }
    if return_paths:
        result["paths"] = values
    return result
