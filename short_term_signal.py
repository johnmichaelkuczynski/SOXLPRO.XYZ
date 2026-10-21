"""Frozen, interpretable 21-session rule study. No fitting at application runtime."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from daily_signal_scorecard import build_rating_history, summarize_ratings
from landing_signal import TIMEFRAMES, TIMEFRAME_WEIGHTS

TRAIN_END = "2018-12-31"
TEST_START = "2019-01-01"
TEST_END = "2026-10-20"
MANIFEST = Path(__file__).parent / "docs" / "short_term_rule.json"

# Fixed small search universe, declared before inspecting holdout outcomes.
# Each candidate has at most three conditions, including confirmation.
CANDIDATES = [
    {"id": "rsi35_recovery", "conditions": [["rsi14", "<=", 35], ["recovery5", "==", True]]},
    {"id": "rsi45_recovery", "conditions": [["rsi14", "<=", 45], ["recovery5", "==", True]]},
    {"id": "ma20_pullback", "conditions": [["dev20", "<=", -.05], ["recovery5", "==", True]]},
    {"id": "ma50_pullback", "conditions": [["dev50", "<=", -.10], ["recovery5", "==", True]]},
    {"id": "five_day_reversal", "conditions": [["return5", "<=", -.08], ["recovery5", "==", True]]},
    {"id": "ten_day_reversal", "conditions": [["return10", "<=", -.15], ["recovery5", "==", True]]},
    {"id": "drawdown_recovery", "conditions": [["drawdown20", "<=", -.15], ["recovery5", "==", True]]},
    {"id": "low_percentile_recovery", "conditions": [["percentile", "<=", 15], ["recovery5", "==", True]]},
    {"id": "bull_pullback", "conditions": [["dev20", "<=", -.05], ["recovery5", "==", True], ["above200", "==", True]]},
    {"id": "bear_rebound", "conditions": [["rsi14", "<=", 45], ["recovery5", "==", True], ["above200", "==", False]]},
    {"id": "bull_rsi_recovery", "conditions": [["rsi14", "<=", 45], ["recovery5", "==", True], ["above200", "==", True]]},
    {"id": "low_range_rsi", "conditions": [["percentile", "<=", 15], ["rsi14", "<=", 45], ["recovery5", "==", True]]},
]


def features(closes):
    c = closes.astype(float).sort_index()
    f = pd.DataFrame(index=c.index)
    for days in (20, 50):
        f[f"dev{days}"] = c / c.rolling(days).mean() - 1
    for days in (5, 10):
        f[f"return{days}"] = c.pct_change(days, fill_method=None)
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    f["rsi14"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    f.loc[(loss == 0) & (gain > 0), "rsi14"] = 100
    f.loc[(loss == 0) & (gain == 0), "rsi14"] = 50
    f["drawdown20"] = c / c.rolling(20).max() - 1
    ma5 = c.rolling(5).mean()
    f["recovery5"] = (c > ma5) & (c.shift() <= ma5.shift())
    ma200 = c.rolling(200).mean()
    f["above200"] = (c > ma200).astype(object).where(ma200.notna())
    weighted = pd.Series(0., index=c.index)
    weights = pd.Series(0., index=c.index)
    for name, sessions in TIMEFRAMES.items():
        window = c.expanding(min_periods=2) if sessions is None else c.rolling(sessions)
        low, high = window.min(), window.max()
        pct = ((c - low) / (high - low).replace(0, np.nan) * 100).clip(0, 100)
        weighted += pct.fillna(0) * TIMEFRAME_WEIGHTS[name]
        weights += pct.notna() * TIMEFRAME_WEIGHTS[name]
    f["percentile"] = weighted / weights.replace(0, np.nan)
    return f


def rule_mask(frame, rule):
    result = pd.Series(True, index=frame.index)
    for name, operator, threshold in rule["conditions"]:
        column = frame[name]
        comparison = column.le(threshold) if operator == "<=" else column.eq(threshold)
        result &= column.notna() & comparison
    return result


def rule_text(rule):
    names = {
        "rsi14": "RSI(14)", "dev20": "close / SMA20 − 1",
        "dev50": "close / SMA50 − 1", "return5": "5-session return",
        "return10": "10-session return", "drawdown20": "drawdown from 20-session highest close",
        "percentile": "long-term percentile",
    }
    text = []
    for name, op, value in rule["conditions"]:
        if name == "recovery5":
            text.append("close crosses back above SMA5 after being at/below it")
        elif name == "above200":
            text.append("close above SMA200" if value else "close at/below SMA200")
        else:
            text.append(f"{names[name]} {op} {value}")
    return " AND ".join(text)


def period_history(history, start, end):
    """Purge incomplete outcomes crossing the training/test boundary."""
    result = history.loc[(history.index >= start) & (history.index <= end)].copy()
    crossing = result["Exit date"].gt(pd.Timestamp(end))
    result.loc[crossing, "Status"] = "Awaiting outcome"
    result.loc[crossing, ["Return", "Worst drawdown"]] = np.nan
    result.attrs = history.attrs.copy()
    return result


def metrics(history, label="BUY", spaced=True):
    summary = summarize_ratings(history, non_overlapping=spaced).set_index("Rating")
    row = summary.loc[label]
    baseline = summary.loc["All rated days"]
    return {
        "observations": int(row["Completed"]),
        "finished_higher_pct": row["Win rate"] * 100,
        "baseline_pct": baseline["Win rate"] * 100,
        "difference_pp": row["Win-rate lift"] * 100,
        "average_return_pct": row["Average return"] * 100,
        "median_return_pct": row["Median return"] * 100,
        "worst_return_pct": row["Worst return"] * 100,
        "average_worst_dip_pct": row["Average drawdown"] * 100,
        "too_thin": int(row["Completed"]) < 20,
    }


def candidate_history(closes, rule, horizon=21):
    f = features(closes)
    ratings = pd.Series("NO EDGE", index=closes.index)
    ratings.loc[rule_mask(f, rule)] = "BUY"
    # Match long-term availability for the all-rated-day baseline.
    ratings.loc[f["percentile"].isna()] = "INSUFFICIENT HISTORY"
    return build_rating_history(closes, horizon, ratings=ratings)


def freeze_training(closes):
    """Only training closes enter selection; no test data is accepted internally."""
    train = closes.loc["2010-03-11":TRAIN_END].copy()
    scores = []
    for rule in CANDIDATES:
        stats = metrics(candidate_history(train, rule))
        scores.append({"rule": rule, "metrics": stats})
    # Predeclared ranking: lift, sample count, median return, then stable ID.
    # Prefer >=20 training observations; if none, still freeze the best
    # exploratory candidate and disclose its thin training evidence.
    eligible = [s for s in scores if s["metrics"]["observations"] >= 20]
    eligible = eligible or [s for s in scores if s["metrics"]["observations"] > 0]
    chosen = max(eligible, key=lambda s: (
        s["metrics"]["difference_pp"], s["metrics"]["observations"],
        s["metrics"]["median_return_pct"], s["rule"]["id"])) if eligible else scores[0]
    return {
        "training_end": TRAIN_END, "test_start": TEST_START, "test_end": TEST_END,
        "training_sha256": hashlib.sha256(train.to_csv().encode()).hexdigest(),
        "rule": chosen["rule"], "rule_text": rule_text(chosen["rule"]),
        "training_metrics": chosen["metrics"], "training_candidates": scores,
        "selection": "Training-only lift ranking; prefer >=20 common-schedule non-overlapping observations.",
        "passed": False, "evaluated": False,
    }


def evaluate_frozen(closes, manifest):
    training = closes.loc["2010-03-11":TRAIN_END]
    # CSV round trips can change last-bit float formatting; compare the
    # provenance hash at a stable precision.
    fingerprint = hashlib.sha256(training.to_csv(float_format="%.10g").encode()).hexdigest()
    if manifest.get("training_stable_sha256") not in (None, fingerprint):
        raise ValueError("Training history changed after freezing; refusing evaluation.")
    history = candidate_history(closes.loc[:TEST_END], manifest["rule"])
    stats = metrics(period_history(history, TEST_START, TEST_END))
    result = dict(manifest)
    result.update(test_metrics=stats, evaluated=True,
                  passed=bool(stats["observations"] >= 30 and stats["difference_pp"] >= 10))
    return result


def load_manifest():
    return json.loads(MANIFEST.read_text())


def short_term_ratings(closes, manifest=None):
    manifest = manifest or load_manifest()
    ratings = pd.Series("NO EDGE", index=closes.index)
    stats = manifest.get("test_metrics", {})
    if (manifest.get("passed") and manifest.get("evaluated")
            and stats.get("observations", 0) >= 30
            and stats.get("difference_pp", -float("inf")) >= 10):
        ratings.loc[rule_mask(features(closes), manifest["rule"])] = "BUY"
    return ratings
