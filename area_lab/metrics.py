"""Small, explicit metrics and inference utilities used by :mod:`area_lab.models`."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def regression_metrics(actual: Any, predicted: Any) -> dict[str, float]:
    """Return regression metrics, using NaN for non-estimable quantities."""

    y = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    mask = np.isfinite(y) & np.isfinite(p)
    y, p = y[mask], p[mask]
    n = len(y)
    result = {
        "n": int(n),
        "r2": np.nan,
        "mae": np.nan,
        "rmse": np.nan,
        "correlation": np.nan,
    }
    if n == 0:
        return result
    result["mae"] = float(np.mean(np.abs(p - y)))
    result["rmse"] = float(np.sqrt(np.mean((p - y) ** 2)))
    if n >= 2 and np.ptp(y) > np.finfo(float).eps:
        ss_total = float(np.sum((y - y.mean()) ** 2))
        if ss_total > 0:
            result["r2"] = float(1.0 - np.sum((y - p) ** 2) / ss_total)
        if np.ptp(p) > np.finfo(float).eps:
            result["correlation"] = float(np.corrcoef(y, p)[0, 1])
    return result


def classification_metrics(
    actual: Any,
    probability: Any,
    *,
    threshold: float | None = None,
) -> dict[str, float]:
    """Compute probability metrics without inventing scores for one class."""

    y = np.asarray(actual, dtype=float)
    prob = np.asarray(probability, dtype=float)
    mask = np.isfinite(y) & np.isfinite(prob)
    y, prob = y[mask].astype(int), prob[mask]
    result = {
        "n": int(len(y)),
        "roc_auc": np.nan,
        "pr_auc": np.nan,
        "brier": np.nan,
        "accuracy": np.nan,
        "precision": np.nan,
        "recall": np.nan,
        "f1": np.nan,
    }
    if len(y) == 0 or len(np.unique(y)) < 2:
        return result
    try:
        from sklearn.metrics import (
            accuracy_score,
            average_precision_score,
            brier_score_loss,
            f1_score,
            precision_score,
            recall_score,
            roc_auc_score,
        )

        labels = (prob >= 0.5).astype(int)
        result.update(
            {
                "roc_auc": float(roc_auc_score(y, prob)),
                "pr_auc": float(average_precision_score(y, prob)),
                "brier": float(brier_score_loss(y, prob)),
                "accuracy": float(accuracy_score(y, labels)),
                "precision": float(precision_score(y, labels, zero_division=np.nan)),
                "recall": float(recall_score(y, labels, zero_division=np.nan)),
                "f1": float(f1_score(y, labels, zero_division=np.nan)),
            }
        )
    except (ImportError, ValueError, FloatingPointError):
        # A missing optional metric implementation is an explicit missing
        # result, never a fabricated zero.
        return result
    return result


def spearman_correlation(actual: Any, predicted: Any) -> float:
    # Reset both indexes: callers commonly pass a datetime-indexed feature
    # series and a NumPy prediction vector, which must be paired by position.
    y = pd.to_numeric(pd.Series(np.asarray(actual)), errors="coerce")
    p = pd.to_numeric(pd.Series(np.asarray(predicted)), errors="coerce")
    mask = y.notna().to_numpy() & p.notna().to_numpy()
    if (
        int(mask.sum()) < 2
        or np.ptp(y.to_numpy()[mask]) <= np.finfo(float).eps
        or np.ptp(p.to_numpy()[mask]) <= np.finfo(float).eps
    ):
        return np.nan
    try:
        return float(y.loc[mask].corr(p.loc[mask], method="spearman"))
    except (TypeError, ValueError):
        return np.nan


def confusion_values(actual: Any, probability: Any) -> dict[str, float]:
    y = np.asarray(actual, dtype=float)
    p = np.asarray(probability, dtype=float)
    mask = np.isfinite(y) & np.isfinite(p)
    y, p = y[mask].astype(int), (p[mask] >= 0.5).astype(int)
    if len(y) == 0 or len(np.unique(y)) < 2:
        return {"tn": np.nan, "fp": np.nan, "fn": np.nan, "tp": np.nan}
    tn = int(np.sum((y == 0) & (p == 0)))
    fp = int(np.sum((y == 0) & (p == 1)))
    fn = int(np.sum((y == 1) & (p == 0)))
    tp = int(np.sum((y == 1) & (p == 1)))
    return {"tn": tn, "fp": fp, "fn": fn, "tp": tp}


def paired_block_bootstrap(
    gains: Any,
    horizon: int,
    *,
    n_bootstrap: int = 200,
    seed: int = 173,
) -> tuple[float, float, float, float]:
    """Bootstrap mean paired loss gains with moving blocks.

    A positive gain means the baseline squared loss exceeded the candidate
    squared loss.  Moving blocks preserve local dependence and have length at
    least the requested forward horizon whenever the sample permits.
    """

    values = np.asarray(gains, dtype=float)
    values = values[np.isfinite(values)]
    n = len(values)
    if n == 0:
        return np.nan, np.nan, np.nan, np.nan
    observed = float(values.mean())
    if n < 2 or n_bootstrap < 2:
        return observed, np.nan, np.nan, np.nan
    block = max(1, min(int(horizon), n))
    rng = np.random.default_rng(seed)
    if block == n:
        samples = np.repeat(observed, n_bootstrap)
    else:
        starts = np.arange(0, n - block + 1)
        samples = np.empty(n_bootstrap, dtype=float)
        for i in range(n_bootstrap):
            values_out: list[float] = []
            while len(values_out) < n:
                start = int(rng.choice(starts))
                values_out.extend(values[start : start + block].tolist())
            samples[i] = float(np.mean(values_out[:n]))
    low, high = np.quantile(samples, [0.025, 0.975])
    # A two-sided bootstrap sign probability is intentionally conservative.
    if observed >= 0:
        p_value = float(2.0 * min(np.mean(samples <= 0), np.mean(samples >= 0)))
    else:
        p_value = float(2.0 * min(np.mean(samples >= 0), np.mean(samples <= 0)))
    return observed, float(low), float(high), min(1.0, p_value)


def paired_loss_inference(
    actual: Any,
    baseline_prediction: Any,
    candidate_prediction: Any,
    horizon: int,
    *,
    n_bootstrap: int = 200,
    seed: int = 173,
) -> dict[str, float]:
    y = np.asarray(actual, dtype=float)
    baseline = np.asarray(baseline_prediction, dtype=float)
    candidate = np.asarray(candidate_prediction, dtype=float)
    mask = np.isfinite(y) & np.isfinite(baseline) & np.isfinite(candidate)
    y, baseline, candidate = y[mask], baseline[mask], candidate[mask]
    if len(y) == 0:
        return {
            "n": 0,
            "relative_rmse_gain": np.nan,
            "mean_squared_loss_gain": np.nan,
            "ci_low": np.nan,
            "ci_high": np.nan,
            "p_value": np.nan,
        }
    baseline_loss = (y - baseline) ** 2
    candidate_loss = (y - candidate) ** 2
    gains = baseline_loss - candidate_loss
    observed, low, high, p_value = paired_block_bootstrap(
        gains,
        horizon,
        n_bootstrap=n_bootstrap,
        seed=seed,
    )
    baseline_rmse = float(np.sqrt(np.mean(baseline_loss)))
    candidate_rmse = float(np.sqrt(np.mean(candidate_loss)))
    relative = (
        (baseline_rmse - candidate_rmse) / baseline_rmse
        if baseline_rmse > np.finfo(float).eps
        else np.nan
    )
    return {
        "n": int(len(y)),
        "relative_rmse_gain": float(relative),
        "mean_squared_loss_gain": float(observed),
        "ci_low": low,
        "ci_high": high,
        "p_value": p_value,
    }
