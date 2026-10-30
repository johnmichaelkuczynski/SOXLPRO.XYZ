"""Fixed K research protocol. No optimizer and no changes to live screening."""
import numpy as np
import pandas as pd

from mean_reversion_model import hurst_rs, k_label


PROTOCOL = {
    "version": 1,
    "lookback": 252,
    "training_end": "2018-12-31",
    "holdout_start": "2019-01-01",
    "data_end": "2026-10-20",
    "stride_sessions": 5,
    "horizons_sessions": [5, 21, 63],
    "primary_horizon_sessions": 21,
    "formula": "R=clip((0.5-H)*200,0,100); T=0 if abs(s)<0.5 else clip(s,-10,10)*10; signed=R*T/100; edge=max(0,signed)",
    "slope": "s=100*(MA200[t]/MA200[t-60]-1)",
    "hurst": "Existing R/S on 252 closing prices' log increments; frozen implementation hash",
    "ranks": "Training-only 1/3 and 2/3 quantiles per score; equality belongs to lower bucket; never split ties",
    "entry": "Next session close after signal; exit h sessions after entry",
    "drawdown": "Worst peak-to-trough decline on daily closes including entry and exit; negative percent",
    "bootstrap": "Paired circular time-block bootstrap, block=ceil((h+1)/5), 2000 replicates, seed=54; exploratory 95% intervals",
    "minimum_nonoverlap": 20,
    "primary_comparison": "High edge-K return minus high trend-only return at 21 sessions, with mean drawdown no worse; require 95% return-difference interval above zero and >=20 non-overlapping observations in both groups",
    "promotion_rule": "Never promote on reused historical data; prospective independent replication required",
    "freshness": "K-specific held-out evaluation only. These dates were examined in other studies; not a genuinely untouched holdout.",
    "scope": "SOXL single-symbol temporal ranks, not cross-sectional investment rankings",
}
SCORES = ("k_edge", "k_signed", "trend", "reversion")
LABELS = (
    "Prime: Growth + Reversion", "Good: Reverting Uptrend",
    "Weak: Mild Reversion, Mild Uptrend", "No Edge: Flat",
    "No Edge: Flat or Random", "Caution: Reverting Downtrend",
    "Value Trap: Strong Reversion, Falling Mean",
    "Avoid: Violent Reversion into Decline",
)


def validate_prices(prices):
    prices = prices.copy()
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise ValueError("Prices require dated daily closes.")
    if prices.index.has_duplicates or not prices.index.is_monotonic_increasing:
        raise ValueError("Dates must be unique and increasing.")
    if not np.isfinite(prices.to_numpy(dtype=float)).all() or (prices <= 0).any():
        raise ValueError("Prices must be finite and positive; missing sessions are not filled.")
    if len(prices) < 261:
        raise ValueError("Insufficient history for causal K snapshots.")
    return prices.astype(float)


def snapshots(prices):
    """Each feature uses only the prefix ending at its signal date."""
    prices = validate_prices(prices)
    rows = []
    for pos in range(259, len(prices), PROTOCOL["stride_sessions"]):
        past = prices.iloc[:pos + 1]
        h = hurst_rs(past.iloc[-252:].to_numpy())
        slope = 100 * (past.iloc[-200:].mean() / past.iloc[-260:-60].mean() - 1)
        trend = 0. if abs(slope) < .5 else float(np.clip(slope, -10, 10) * 10)
        reversion = None if h is None else float(np.clip((.5-h)*200, 0, 100))
        signed = None if reversion is None else reversion * trend / 100
        rows.append(dict(position=pos, date=prices.index[pos], H=h, trend=trend,
                         reversion=reversion, k_signed=signed,
                         k_edge=None if signed is None else max(0., signed),
                         label=k_label(signed, trend)))
    return pd.DataFrame(rows)


def fit_cutoffs(features):
    train = features.loc[features.date <= pd.Timestamp(PROTOCOL["training_end"])]
    train = train.dropna(subset=list(SCORES))
    if len(train) < 60:
        raise ValueError("Fewer than 60 usable training snapshots; ranks unavailable.")
    return {score: train[score].quantile([1/3, 2/3]).tolist() for score in SCORES}


def assign_ranks(features, cutoffs):
    result = features.copy()
    for score in SCORES:
        # searchsorted(side=left) deliberately keeps all tied zeros together.
        result[score + "_rank"] = [
            None if pd.isna(x) else ("Low", "Middle", "High")[
                np.searchsorted(cutoffs[score], x, side="left")]
            for x in result[score]
        ]
    return result


def outcomes(prices, features, horizon):
    rows = []
    for row in features.to_dict("records"):
        entry = row["position"] + 1
        end = entry + horizon
        if end >= len(prices):
            continue
        path = prices.iloc[entry:end + 1].to_numpy()
        end_date = prices.index[end]
        partition = ("training" if end_date <= pd.Timestamp(PROTOCOL["training_end"])
                     else "holdout" if row["date"] >= pd.Timestamp(PROTOCOL["holdout_start"])
                     else "purged")
        rows.append(dict(row, horizon=horizon, entry_date=prices.index[entry],
                         end_date=end_date, partition=partition,
                         return_pct=float(100*(path[-1]/path[0]-1)),
                         drawdown_pct=float(100*np.min(path/np.maximum.accumulate(path)-1))))
    return pd.DataFrame(rows)


def nonoverlap_mask(frame):
    """Greedy disjoint holding intervals, selected without consulting outcomes."""
    keep = np.zeros(len(frame), dtype=bool)
    last_end = pd.Timestamp.min
    for i, row in enumerate(frame.itertuples()):
        if row.entry_date > last_end:
            keep[i] = True
            last_end = row.end_date
    return keep


def summarize(frame, horizon, replicates=2000):
    """Resample the same time blocks for all selectors, including baselines."""
    if frame.empty:
        raise ValueError("No matured holdout outcomes.")
    data = frame.loc[frame.partition == "holdout"].sort_values("date").reset_index(drop=True)
    usable = data[list(SCORES)].notna().all(axis=1).to_numpy()
    groups = {"Unconditional": usable}
    for score in SCORES:
        for rank in ("Low", "Middle", "High"):
            groups[f"{score}: {rank}"] = usable & data[score + "_rank"].eq(rank).to_numpy()
    for label in LABELS:
        groups["Label: " + label] = usable & data.label.eq(label).to_numpy()
    if data.empty:
        raise ValueError("No matured holdout outcomes.")
    n = len(data)
    block = int(np.ceil((horizon + 1)/PROTOCOL["stride_sessions"]))
    rng = np.random.default_rng(54)
    starts = rng.integers(0, n, size=(replicates, int(np.ceil(n/block))))
    indices = ((starts[:, :, None] + np.arange(block)) % n).reshape(replicates, -1)[:, :n]
    disjoint = nonoverlap_mask(data)
    returns = data.return_pct.to_numpy()
    drawdowns = data.drawdown_pct.to_numpy()
    draws = {}
    summaries = []
    for name, mask in groups.items():
        resampled = mask[indices]
        counts = resampled.sum(axis=1)
        def boot(values):
            return np.divide((values[indices]*resampled).sum(axis=1), counts,
                             out=np.full(replicates, np.nan), where=counts > 0)
        draws[name] = (boot(returns), boot(drawdowns))
        selected = data.loc[mask]
        independent = data.loc[mask & disjoint]
        summaries.append(dict(
            horizon=horizon, group=name, count=len(selected), nonoverlap_count=len(independent),
            mean_return_pct=selected.return_pct.mean(), median_return_pct=selected.return_pct.median(),
            mean_drawdown_pct=selected.drawdown_pct.mean(), worst_drawdown_pct=selected.drawdown_pct.min(),
            nonoverlap_return_pct=independent.return_pct.mean(),
            nonoverlap_drawdown_pct=independent.drawdown_pct.mean(),
            status="Insufficient sample" if len(independent) < 20 else "Exploratory only",
        ))
    summary = pd.DataFrame(summaries).set_index("group")
    comparisons = []
    for name in groups:
        for baseline in ("Unconditional", "trend: High", "reversion: High"):
            if name == baseline:
                continue
            enough = min(summary.loc[name, "nonoverlap_count"],
                         summary.loc[baseline, "nonoverlap_count"]) >= 20
            item = dict(horizon=horizon, group=name, baseline=baseline)
            for metric, slot in (("return", 0), ("drawdown", 1)):
                delta = draws[name][slot] - draws[baseline][slot]
                finite = delta[np.isfinite(delta)]
                valid = enough and len(finite) >= .95*replicates
                lo, hi = np.quantile(finite, [.025, .975]) if valid else (np.nan, np.nan)
                item.update({
                    metric + "_difference_pp": summary.loc[name, "mean_" + metric + "_pct"] -
                    summary.loc[baseline, "mean_" + metric + "_pct"],
                    metric + "_ci_low": lo, metric + "_ci_high": hi,
                })
            item["status"] = "Exploratory; not multiplicity-adjusted" if enough else "Insufficient sample; interval withheld"
            comparisons.append(item)
    return summary.reset_index(), pd.DataFrame(comparisons)
