"""Exploratory, causal range-position analogues, not a calibrated trading rule."""
import numpy as np
import pandas as pd

from landing_signal import TIMEFRAMES, TIMEFRAME_WEIGHTS


def prepare_history(closes):
    values = pd.to_numeric(pd.Series(closes), errors="coerce")
    values = values[np.isfinite(values) & (values > 0)].sort_index()
    values = values[~values.index.duplicated(keep="last")]
    frame = pd.DataFrame({"close": values})
    numerator = pd.Series(0.0, index=values.index)
    denominator = numerator.copy()
    for label, sessions in TIMEFRAMES.items():
        window = values.expanding(min_periods=2) if sessions is None else values.rolling(sessions)
        low, high = window.min(), window.max()
        valid = high > low
        score = ((values - low) / (high - low)).clip(0, 1) * 100
        weight = TIMEFRAME_WEIGHTS[label]
        numerator += score.where(valid, 0).fillna(0) * weight
        denominator += valid.astype(float) * weight
        frame[f"low:{label}"], frame[f"high:{label}"] = low, high
    frame["score"] = numerator / denominator.replace(0, np.nan)
    # At least one full year of trailing history before selecting an analogue.
    frame.loc[frame.index[:251], "score"] = np.nan
    return frame


def estimate(prepared, selected_price, horizon):
    if horizon not in (21, 126, 252):
        raise ValueError("Choose one, six, or twelve months.")
    if not np.isfinite(selected_price) or not 1 <= selected_price <= 500:
        raise ValueError("Choose a starting price between $1 and $500.")
    result = dict(score=np.nan, count=0, supported=False, reason="Not enough price history.",
                  probability=None, median_return=None, low_return=None, high_return=None,
                  upside_return=None, ci_low=None, ci_high=None, history_date="")
    if prepared.empty:
        return result
    result["history_date"] = str(pd.Timestamp(prepared.index[-1]).date())
    latest = prepared.iloc[-1]
    scores, weights = [], []
    for label in TIMEFRAMES:
        low, high = latest[f"low:{label}"], latest[f"high:{label}"]
        if np.isfinite(low) and np.isfinite(high) and high > low:
            scores.append(np.clip((selected_price - low) / (high - low), 0, 1) * 100)
            weights.append(TIMEFRAME_WEIGHTS[label])
    if not weights:
        return result
    target = float(np.average(scores, weights=weights))
    result["score"] = target
    # Do not extrapolate beyond the observed price range with clipped scores.
    if not prepared["close"].min() <= selected_price <= prepared["close"].max():
        result["reason"] = "This price is outside the observed historical range; reliable analogues are unavailable."
        return result
    forward = prepared["close"].shift(-horizon) / prepared["close"] - 1
    matches = np.flatnonzero(
        ((prepared["score"] - target).abs() <= 10).to_numpy()
        & np.isfinite(forward.to_numpy())
    )
    chosen, next_allowed = [], 0
    for position in matches:
        if position >= next_allowed:
            chosen.append(position)
            next_allowed = position + horizon
    result["count"] = len(chosen)
    if len(chosen) < 10:
        result["reason"] = (
            f"Too little comparable history: {len(chosen)} non-overlapping observations; "
            "at least 10 are required. No probability or price forecast is shown."
        )
        return result
    returns = forward.iloc[chosen].to_numpy()
    p, n, z = float(np.mean(returns > 0)), len(returns), 1.96
    center = (p + z*z/(2*n))/(1+z*z/n)
    half = z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    low, median, high = np.quantile(returns, [0.1, 0.5, 0.9])
    positive = returns[returns > 0]
    result.update(supported=True, reason="", probability=p, median_return=float(median),
                  low_return=float(low), high_return=float(high),
                  upside_return=float(np.median(positive)) if len(positive) else None,
                  ci_low=float(center-half), ci_high=float(center+half))
    return result
