"""Frozen, causal evaluation of the existing exploratory slider estimator."""
import numpy as np
import pandas as pd

from price_scenario_model import estimate, prepare_history

PROTOCOL = {
    "version": 1,
    "holdout_start": "2019-01-01",
    "horizons": [21, 126, 252],
    "matching": "Existing estimator, +/-10 score points, earliest-first nonoverlap, minimum 10",
    "origins": "First holdout session then every horizon sessions; never reschedule abstentions",
    "entry": "Observed origin close within slider bounds; no rounding; close-to-close outcome",
    "training": "Expanding history ending at origin; only outcomes matured by origin",
    "baseline": "Unconditional finite-score origins, earliest-first nonoverlap, minimum 10",
    "interval": "10th/90th empirical quantiles (nominal 80%)",
    "calibration_bins": [0, .2, .4, .6, .8, 1],
    "uncertainty": "95% Wilson event intervals and paired circular block bootstrap, 3 origins/block, 2000 draws, seed 48",
    "claims": "Exploratory only; no tuning or promotion using this holdout",
}


def walk_forward(closes):
    prepared = prepare_history(closes)
    if not isinstance(prepared.index, pd.DatetimeIndex):
        raise ValueError("Dated closing prices are required.")
    positions = np.flatnonzero(prepared.index >= pd.Timestamp(PROTOCOL["holdout_start"]))
    rows = []
    if not len(positions):
        return pd.DataFrame()
    for h in PROTOCOL["horizons"]:
        for i in range(int(positions[0]), len(prepared), h):
            past = prepared.iloc[:i + 1]
            price = float(past.close.iloc[-1])
            row = dict(horizon=h, origin=str(past.index[-1].date()), entry=price,
                       status="pending", training_end=str(past.index[-1].date()))
            # Emit forecasts even for pending outcomes, but never score them.
            forecast = estimate(past, price, h) if 1 <= price <= 500 else {
                "supported": False, "count": 0, "reason": "Outside slider bounds"}
            forward = past.close.shift(-h) / past.close - 1
            candidates = np.flatnonzero(np.isfinite(past.score) & np.isfinite(forward))
            chosen, next_allowed = [], 0
            for j in candidates:
                if j >= next_allowed:
                    chosen.append(j)
                    next_allowed = j + h
            row.update(count=forecast["count"], baseline_count=len(chosen),
                       reason=forecast.get("reason", ""))
            if forecast["supported"] and len(chosen) >= 10:
                unconditional = forward.iloc[chosen].to_numpy()
                row.update(probability=forecast["probability"],
                           low=forecast["low_return"], high=forecast["high_return"],
                           baseline_probability=float(np.mean(unconditional > 0)),
                           baseline_low=float(np.quantile(unconditional, .1)),
                           baseline_high=float(np.quantile(unconditional, .9)))
            else:
                row["status"] = "unsupported"
            if i + h < len(prepared):
                row["end"] = str(prepared.index[i + h].date())
                row["return"] = float(prepared.close.iloc[i + h] / price - 1)
                if row["status"] != "unsupported":
                    row["status"] = "scored"
            rows.append(row)
    return pd.DataFrame(rows)


def wilson(values):
    n = len(values)
    if not n:
        return [None, None]
    p, z = float(np.mean(values)), 1.96
    center = (p + z*z/(2*n))/(1+z*z/n)
    half = z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    return [float(center-half), float(center+half)]


def block_interval(values):
    """Approximate dependence-aware uncertainty, not IID daily-trade precision."""
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < 6:
        return [None, None]
    rng = np.random.default_rng(48)
    starts = rng.integers(0, n, size=(2000, (n + 2)//3))
    indices = ((starts[..., None] + np.arange(3)) % n).reshape(2000, -1)[:, :n]
    return np.quantile(values[indices].mean(axis=1), [.025, .975]).tolist()


def summarize(predictions):
    summary, calibration = [], []
    for h in PROTOCOL["horizons"]:
        group = predictions[predictions.horizon == h]
        scored = group[group.status == "scored"]
        row = dict(horizon=h, scheduled=len(group), scored=len(scored),
                   unsupported=int((group.status == "unsupported").sum()),
                   pending=int((group.status == "pending").sum()))
        if len(scored):
            y = (scored["return"].to_numpy() > 0).astype(float)
            row["observed_higher"] = float(y.mean())
            row["observed_higher_wilson95"] = wilson(y)
            losses = {}
            for label, prefix in (("matched", ""), ("unconditional", "baseline_")):
                p = scored[prefix+"probability"].to_numpy()
                lo, hi, r = scored[prefix+"low"].to_numpy(), scored[prefix+"high"].to_numpy(), scored["return"].to_numpy()
                coverage = ((r >= lo) & (r <= hi)).astype(float)
                brier = (p-y)**2
                # Proper interval score for an 80% prediction interval.
                interval_score = hi-lo + 10*np.maximum(lo-r, 0) + 10*np.maximum(r-hi, 0)
                losses[label] = (brier, interval_score)
                row[label] = dict(mean_probability=float(p.mean()), brier=float(brier.mean()),
                                  calibration_bias=float((p-y).mean()),
                                  calibration_bias_block95=block_interval(p-y),
                                  coverage=float(coverage.mean()), coverage_wilson95=wilson(coverage),
                                  coverage_block95=block_interval(coverage),
                                  mean_width=float((hi-lo).mean()),
                                  interval_score=float(interval_score.mean()))
                bins = np.minimum((p*5).astype(int), 4)
                for b in range(5):
                    mask = bins == b
                    calibration.append(dict(horizon=h, model=label, bin_low=b/5, bin_high=(b+1)/5,
                                            n=int(mask.sum()),
                                            predicted=float(p[mask].mean()) if mask.any() else None,
                                            observed=float(y[mask].mean()) if mask.any() else None,
                                            observed_wilson95=wilson(y[mask])))
            for k, metric in enumerate(("brier", "interval_score")):
                delta = losses["matched"][k] - losses["unconditional"][k]
                row[metric+"_delta"] = float(delta.mean())
                row[metric+"_delta_block95"] = block_interval(delta)
        summary.append(row)
    return summary, calibration
