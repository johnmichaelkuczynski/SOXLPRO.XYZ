"""Simulation reference for R/S estimates; never adjusts H, scores, or half-life."""
from functools import lru_cache
import hashlib
import inspect
import json
from pathlib import Path

import numpy as np


REFERENCE = Path(__file__).parent / "reports/hurst_uncertainty/reference.json"
WINDOWS = (100, 252, 500)  # closing prices, hence N-1 increments


def estimator_fingerprint():
    from mean_reversion_model import hurst_rs
    return hashlib.sha256(inspect.getsource(hurst_rs).encode()).hexdigest()


def rs_batch(increments):
    """Vectorized replica of hurst_rs for simulation, checked against that API."""
    x = np.asarray(increments, dtype=float)
    scales = np.unique(np.geomspace(8, x.shape[1] // 2, 9).astype(int))
    ratios = []
    for size in scales:
        blocks = x[:, :x.shape[1] // size * size].reshape(len(x), -1, size)
        cumulative = np.cumsum(blocks - blocks.mean(axis=2, keepdims=True), axis=2)
        ranges = np.maximum(cumulative.max(axis=2), 0) - np.minimum(cumulative.min(axis=2), 0)
        ratios.append((ranges / blocks.std(axis=2, ddof=1)).mean(axis=1))
    return np.polyfit(np.log(scales), np.log(ratios), 1)[0]


def fractional_gaussian_increments(rng, count, observations, h):
    """Exact finite-dimensional fGn covariance, not an AR(1) proxy for H."""
    n = observations - 1
    k = np.arange(n, dtype=float)
    covariance = .5 * (np.abs(k - 1)**(2*h) - 2*k**(2*h) + (k + 1)**(2*h))
    indices = np.abs(np.arange(n)[:, None] - np.arange(n)[None, :])
    factor = np.linalg.cholesky(covariance[indices])
    return rng.standard_normal((count, n)) @ factor.T


@lru_cache(maxsize=1)
def load_reference():
    data = json.loads(REFERENCE.read_text())
    if data["estimator_sha256"] != estimator_fingerprint():
        raise ValueError("R/S estimator changed; regenerate the simulation reference.")
    return data


def hurst_evidence(h, observations):
    """One-sided Monte Carlo test against iid Gaussian random-walk increments.

    The simulation range is a sampling reference, NOT a CI for a stock's true H.
    Unsupported counts are explicit: no nearest-window substitution.
    """
    result = dict(label="N/A", p_lower=None, null_range=None, null_bias=None,
                  reason="", simulations=None)
    if h is None or not np.isfinite(h):
        result["reason"] = "H unavailable."
        return result
    if observations not in WINDOWS:
        result["reason"] = "Simulation evidence requires exactly 100, 252 or 500 closes."
        return result
    try:
        reference = load_reference()
        samples = np.asarray(reference["null_samples"][str(observations)], dtype=float)
        if samples.ndim != 1 or len(samples) < 1000 or not np.isfinite(samples).all():
            raise ValueError("Invalid null reference.")
        p = (1 + np.count_nonzero(samples <= h)) / (len(samples) + 1)
        result.update(
            label="Anti-persistence evidence" if h < .5 and p <= .05 else "Not distinguished from noise",
            p_lower=float(p),
            null_range=np.quantile(samples, [.025, .975]).tolist(),
            null_bias=float(samples.mean() - .5),
            simulations=len(samples),
            reason="Single-window Gaussian random-walk comparison; not a profit probability or stationarity test.",
        )
    except (OSError, ValueError, KeyError, TypeError):
        result["reason"] = "Simulation reference unavailable or outdated; evidence cannot be assessed."
    return result
