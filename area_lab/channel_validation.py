"""Frozen, causal research protocol; independent of the existing signal study."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
from scipy.special import log_ndtr, ndtr
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

PROTOCOL = {
    "version": 1,
    "horizons_sessions": [21, 63, 126, 252],
    "origin_stride_sessions": 21,
    "minimum_channel_sessions": 252,
    "minimum_training_origins": 60,
    "channel": "Expanding log-price OLS slope; median/min/max intercept, matching chart defaults.",
    "target": "Fixed price on each refitted channel at the deadline, not a moving barrier.",
    "outcome": "Directional touch on a subsequent adjusted daily CLOSE, excluding origin close.",
    "area": "20-session rectangle: elapsed calendar days times absolute log10 price change; signed companion.",
    "baseline": "Lognormal first-passage estimate; expanding daily log-return mean and variance, annualized by 252.",
    "models": "Raw lognormal; logistic calibration on baseline logit; same calibration plus signed and unsigned area.",
    "fitting": "StandardScaler and L2 logistic regression C=1 fitted anew using only matured earlier windows.",
    "uncertainty": "Paired moving-block bootstrap by forecast date; block length ceil(horizon/21), 1000 draws.",
    "status": "Exploratory walk-forward study, not a new untouched holdout or trading recommendation.",
}


def clean_prices(prices: pd.Series) -> pd.Series:
    values = pd.Series(prices, copy=True).astype(float)
    values.index = pd.to_datetime(values.index)
    if values.index.has_duplicates or not values.index.is_monotonic_increasing:
        raise ValueError("Price dates must be unique and increasing.")
    if values.isna().any() or not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("All prices must be finite, positive adjusted closes.")
    return values


def first_passage(log_barrier: float, drift: float, sigma: float, years: float) -> float:
    """Direction-aware first touch, equivalent to the chart's lognormal model."""
    if years <= 0 or sigma <= 0:
        raise ValueError("Positive horizon and volatility required.")
    if abs(log_barrier) < 1e-12:
        return 1.0
    distance = abs(log_barrier)
    direction = 1 if log_barrier > 0 else -1
    mu = direction * drift
    denom = sigma * math.sqrt(years)
    reflected = 2 * mu * distance / sigma**2 + log_ndtr((-mu * years - distance) / denom)
    return float(np.clip(ndtr((mu * years - distance) / denom) +
                         math.exp(min(0.0, reflected)), 0, 1))


def forecast_at(history: pd.Series, deadline: pd.Timestamp) -> list[dict]:
    """No future prices accepted by this API."""
    history = clean_prices(history)
    if len(history) < 252:
        raise ValueError("At least 252 past sessions required.")
    deadline = pd.Timestamp(deadline)
    if deadline <= history.index[-1]:
        raise ValueError("Deadline must follow the prediction date.")
    log_prices = np.log(history.to_numpy())
    days = (history.index - history.index[0]).total_seconds().to_numpy() / 86400
    centered = days - days.mean()
    slope = float(centered @ (log_prices - log_prices.mean()) / (centered @ centered))
    residual = log_prices - slope * days
    future_day = (deadline - history.index[0]).total_seconds() / 86400
    returns = np.diff(log_prices)
    drift, sigma = float(returns.mean() * 252), float(returns.std(ddof=1) * np.sqrt(252))
    elapsed = (history.index[-1] - history.index[-21]).days
    signed_area = elapsed * (log_prices[-1] - log_prices[-21]) / math.log(10)
    years = (deadline - history.index[-1]).total_seconds() / (365.25 * 86400)
    rows = []
    for name, intercept in (("Lower", residual.min()), ("Median", np.median(residual)),
                            ("Upper", residual.max())):
        log_target = float(intercept + slope * future_day)
        barrier = log_target - log_prices[-1]
        rows.append({
            "line": name, "origin": history.index[-1], "deadline": deadline,
            "fit_start": history.index[0], "fit_end": history.index[-1],
            "fit_sessions": len(history), "target_price": math.exp(log_target),
            "log_target": log_target, "direction": "up" if barrier >= 0 else "down",
            "raw_probability": first_passage(barrier, drift, sigma, years),
            "area": abs(signed_area), "signed_area": signed_area,
        })
    return rows


def build_windows(prices: pd.Series) -> pd.DataFrame:
    prices = clean_prices(prices)
    rows = []
    for horizon in PROTOCOL["horizons_sessions"]:
        for origin in range(251, len(prices) - horizon, PROTOCOL["origin_stride_sessions"]):
            deadline = origin + horizon
            forecasts = forecast_at(prices.iloc[:origin + 1], prices.index[deadline])
            # Outcomes never enter forecast_at; today's close is NOT a future hit.
            future = np.log(prices.iloc[origin + 1:deadline + 1].to_numpy())
            for row in forecasts:
                row.update(horizon=horizon, origin_pos=origin, deadline_pos=deadline)
                row["hit"] = int(
                    future.max() >= row["log_target"] if row["direction"] == "up"
                    else future.min() <= row["log_target"]
                )
                rows.append(row)
    return pd.DataFrame(rows)


def design(frame: pd.DataFrame, area: bool) -> np.ndarray:
    p = np.clip(frame.raw_probability.to_numpy(), 1e-6, 1 - 1e-6)
    columns = [np.log(p / (1 - p))]
    if area:
        columns += [frame.area.to_numpy(), frame.signed_area.to_numpy()]
    return np.column_stack(columns)


def walk_forward(windows: pd.DataFrame) -> pd.DataFrame:
    """Maturity-purged fitting; no scaler, labels or coefficients from the future."""
    output = []
    if windows.empty:
        return pd.DataFrame()
    for _, group in windows.groupby("horizon", sort=True):
        for origin, current in group.groupby("origin", sort=True):
            train = group[(group.origin < origin) & (group.deadline <= origin)]
            if train.origin.nunique() < PROTOCOL["minimum_training_origins"] or train.hit.nunique() < 2:
                continue
            result = current.copy()
            for name, with_area in (("calibrated_probability", False), ("area_probability", True)):
                model = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000))
                model.fit(design(train, with_area), train.hit)
                result[name] = model.predict_proba(design(current, with_area))[:, 1]
            result["training_origins"] = train.origin.nunique()
            result["training_last_outcome"] = train.deadline.max()
            output.append(result)
    return pd.concat(output, ignore_index=True) if output else pd.DataFrame()


def gain_interval(frame: pd.DataFrame, other: str) -> tuple[float, float]:
    """Resample paired losses, retaining same-date cross-line dependence."""
    gains = (frame.hit - frame[other])**2 - (frame.hit - frame.area_probability)**2
    by_date = gains.groupby(frame.origin).mean().sort_index().to_numpy()
    block = math.ceil(int(frame.horizon.iloc[0]) / 21)
    if len(by_date) < 2 * block:
        return float("nan"), float("nan")
    rng = np.random.default_rng(1729)
    estimates = []
    for _ in range(1000):
        starts = rng.integers(0, len(by_date) - block + 1, math.ceil(len(by_date) / block))
        sample = np.concatenate([by_date[start:start + block] for start in starts])[:len(by_date)]
        estimates.append(sample.mean())
    return tuple(np.quantile(estimates, [.025, .975]).tolist())


def summarize(predictions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary, calibration = [], []
    if predictions.empty:
        return pd.DataFrame(), pd.DataFrame()
    models = {"Lognormal": "raw_probability", "Calibrated lognormal": "calibrated_probability",
              "Calibrated lognormal + area": "area_probability"}
    for (horizon, line), group in predictions.groupby(["horizon", "line"]):
        # Descriptive subset with no shared future sessions within this line/horizon.
        nonoverlap, last_end = [], -1
        for idx, row in group.sort_values("origin_pos").iterrows():
            if row.origin_pos >= last_end:
                nonoverlap.append(idx)
                last_end = row.deadline_pos
        ci_raw = gain_interval(group, "raw_probability")
        ci_cal = gain_interval(group, "calibrated_probability")
        for name, column in models.items():
            subset = group.loc[nonoverlap]
            summary.append({
                "horizon_sessions": horizon, "line": line, "model": name,
                "forecasts": len(group), "first_origin": group.origin.min(),
                "last_origin": group.origin.max(), "observed_hit_rate": group.hit.mean(),
                "mean_predicted_probability": group[column].mean(),
                "brier": ((group.hit - group[column])**2).mean(),
                "classification_accuracy": ((group[column] >= .5) == group.hit).mean(),
                "nonoverlap_forecasts": len(subset),
                "nonoverlap_hit_rate": subset.hit.mean(),
                "nonoverlap_brier": ((subset.hit - subset[column])**2).mean(),
                "area_gain_vs_raw_ci_low": ci_raw[0], "area_gain_vs_raw_ci_high": ci_raw[1],
                "area_gain_vs_calibrated_ci_low": ci_cal[0],
                "area_gain_vs_calibrated_ci_high": ci_cal[1],
            })
            bins = pd.cut(group[column], [0, .2, .4, .6, .8, 1], include_lowest=True)
            for bucket, rows in group.groupby(bins, observed=True):
                calibration.append({
                    "horizon_sessions": horizon, "line": line, "model": name,
                    "probability_bin": str(bucket), "forecasts": len(rows),
                    "mean_probability": rows[column].mean(), "observed_hit_rate": rows.hit.mean(),
                })
    return pd.DataFrame(summary), pd.DataFrame(calibration)
