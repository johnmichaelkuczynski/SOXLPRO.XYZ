"""Classical rescaled-range estimates from daily close-to-close log increments."""
import numpy as np
from landing_signal import completed_close_history


def hurst_rs(prices):
    changes = np.diff(np.log(np.asarray(prices, dtype=float)))
    scales = np.unique(np.geomspace(8, len(changes)//2, 9).astype(int))
    sizes, ratios = [], []
    for size in scales:
        blocks = changes[:len(changes)//size*size].reshape(-1, size)
        deviations = blocks - blocks.mean(axis=1, keepdims=True)
        cumulative = np.cumsum(deviations, axis=1)
        ranges = np.maximum(cumulative.max(axis=1), 0) - np.minimum(cumulative.min(axis=1), 0)
        std = blocks.std(axis=1, ddof=1)
        valid = (std > 1e-12) & (ranges > 0)
        if valid.any():
            sizes.append(size)
            ratios.append(np.mean(ranges[valid]/std[valid]))
    if len(sizes) < 3:
        return None
    h = float(np.polyfit(np.log(sizes), np.log(ratios), 1)[0])
    # Raw finite-sample estimates are not clipped; only the score is bounded.
    return h if np.isfinite(h) else None


def analyze(frame, lookback=252):
    if not 100 <= lookback <= 500:
        raise ValueError("Lookback must be between 100 and 500 sessions.")
    closes = completed_close_history(frame).iloc[-int(lookback):]
    result = dict(H=None, score=None, half_life=None, count=len(closes),
                  date=str(closes.index[-1].date()) if len(closes) else "",
                  reason="")
    if len(closes) < 100:
        result["reason"] = "Fewer than 100 daily closing prices."
        return result
    values = closes.to_numpy(dtype=float)
    h = hurst_rs(values)
    if h is None:
        result["reason"] = "Insufficient price variation for R/S estimation."
        return result
    result.update(H=h, score=float(np.clip((.5-h)*200, 0, 100)))
    lagged, changes = values[:-1], np.diff(values)
    if np.std(lagged) > 1e-12:
        slope = float(np.polyfit(lagged, changes, 1)[0])
        theta = -slope
        if 0 < theta < 1:
            result["half_life"] = float(np.log(2)/theta)
        else:
            result["reason"] = "No stable positive mean-reversion speed in the price-level regression."
    return result
