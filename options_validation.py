"""Walk-forward audit of historical SOXL option snapshots, never a claim gate.

Inputs are observed snapshots, not option trades, synthetic quotes or today's IV.
See docs/options-validation.md for the point-in-time data contract.
"""
from dataclasses import asdict, dataclass
import hashlib
import json

import numpy as np
import pandas as pd

from options_projection_model import price, project


@dataclass(frozen=True)
class StudyConfig:
    horizons: tuple = (5, 10, 20)
    samples: int = 2000
    fee_per_contract: float = .65
    slippage_per_share: float = .01
    max_quote_age_seconds: int = 900
    max_dte: int = 180
    min_group_size: int = 30


def american_price(spot, strike, years, iv, rate, dividend, kind, steps=300):
    """CRR American tree with continuous yield; NOT discrete-dividend valuation."""
    if kind not in ("call", "put") or not all(np.isfinite(
            [spot, strike, years, iv, rate, dividend])):
        raise ValueError("Invalid American pricing inputs.")
    if spot <= 0 or strike <= 0 or iv <= 0 or steps < 2:
        raise ValueError("Positive prices/IV and at least two tree steps are required.")
    if years <= 0:
        return float(max(spot-strike if kind == "call" else strike-spot, 0))
    dt = years / steps
    up = np.exp(iv*np.sqrt(dt))
    down = 1/up
    probability = (np.exp((rate-dividend)*dt)-down)/(up-down)
    if not 0 <= probability <= 1:
        raise ValueError("American tree probability outside [0,1].")
    sign = 1 if kind == "call" else -1
    grid = spot * up**np.arange(steps+1) * down**np.arange(steps, -1, -1)
    values = np.maximum(sign*(grid-strike), 0)
    for n in range(steps-1, -1, -1):
        grid = spot * up**np.arange(n+1) * down**np.arange(n, -1, -1)
        values = np.maximum(
            np.exp(-rate*dt)*((1-probability)*values[:-1] + probability*values[1:]),
            np.maximum(sign*(grid-strike), 0),
        )
    return float(values[0])


def _timestamps(frame, columns):
    for col in columns:
        # Reject naive dates rather than silently assigning them UTC.
        if frame[col].isna().any() or any(pd.Timestamp(v).tzinfo is None for v in frame[col]):
            raise ValueError(f"{col} must contain timezone-aware timestamps.")
        frame[col] = pd.to_datetime(frame[col], utc=True, errors="raise")


def prepare_data(history, quotes):
    history, quotes = history.copy(), quotes.copy()
    hcols = {"timestamp", "available_at", "Close"}
    qcols = {"ticker", "timestamp", "quote_time", "spot_time", "iv_time",
             "rate_time", "dividend_time", "expiration", "type", "strike",
             "spot", "iv", "bid", "ask", "rate", "dividend", "multiplier", "source"}
    if hcols-set(history) or qcols-set(quotes):
        raise ValueError(f"Missing columns: history {sorted(hcols-set(history))}; "
                         f"quotes {sorted(qcols-set(quotes))}.")
    if history.empty or quotes.empty:
        raise ValueError("Historical underlying and option quotes are both required.")
    _timestamps(history, ["timestamp", "available_at"])
    _timestamps(quotes, ["timestamp", "quote_time", "spot_time", "iv_time",
                         "rate_time", "dividend_time"])
    if history.timestamp.duplicated().any() or quotes.duplicated(["ticker", "timestamp"]).any():
        raise ValueError("Duplicate observations are not allowed.")
    if (history.available_at < history.timestamp).any():
        raise ValueError("Underlying observations cannot be available before observation time.")
    history["Close"] = pd.to_numeric(history.Close, errors="raise")
    if not np.isfinite(history.Close).all() or (history.Close <= 0).any():
        raise ValueError("Underlying prices must be finite and positive.")
    if quotes.source.isna().any() or quotes.source.astype(str).str.strip().eq("").any():
        raise ValueError("Each historical quote needs a source.")
    if quotes.ticker.isna().any() or quotes.ticker.astype(str).str.strip().eq("").any():
        raise ValueError("Each historical quote needs a contract ticker.")
    if "adjusted" in quotes and not quotes.adjusted.astype(str).str.lower().isin(["false", "0"]).all():
        raise ValueError("Adjusted/nonstandard contracts are not supported.")
    for col in ["strike", "spot", "iv", "bid", "ask", "rate", "dividend", "multiplier"]:
        quotes[col] = pd.to_numeric(quotes[col], errors="raise")
        if not np.isfinite(quotes[col]).all():
            raise ValueError(f"Non-finite {col}.")
    if ((quotes[["strike", "spot", "iv", "ask"]] <= 0).any().any()
            or (quotes.bid < 0).any() or (quotes.ask < quotes.bid).any()
            or (quotes.multiplier != 100).any() or (quotes.dividend < 0).any()
            or not quotes.type.isin(["call", "put"]).all()):
        raise ValueError("Invalid quotes, IV or nonstandard contract.")
    quotes["expiration"] = pd.to_datetime(quotes.expiration, errors="raise").dt.date
    if quotes.expiration.isna().any():
        raise ValueError("Expiration is required.")
    for _, group in quotes.groupby("ticker"):
        if any(group[c].nunique() != 1 for c in ["expiration", "type", "strike", "multiplier"]):
            raise ValueError("Contract terms changed within a ticker.")
    # Study uses regular 16:00 NY closes only; exclude early-close sessions from
    # the supplied session manifest rather than pretending they close at 16:00.
    local = quotes.timestamp.dt.tz_convert("America/New_York")
    if ((local.dt.hour != 16) | (local.dt.minute != 0) | (local.dt.second != 0)).any():
        raise ValueError("Quote timestamp must be the regular 16:00 New York study cutoff.")
    return history.sort_values("timestamp"), quotes.sort_values(["timestamp", "ticker"])


def _valid_snapshot(row, config):
    for field in ["quote_time", "spot_time", "iv_time"]:
        age = (row.timestamp-row[field]).total_seconds()
        if not 0 <= age <= config.max_quote_age_seconds:
            return "future or stale quote/spot/IV"
    if row.rate_time > row.timestamp or row.dividend_time > row.timestamp:
        return "future rate/dividend assumption"
    return None


def _summary(rows, minimum):
    p = np.array([r["probability"] for r in rows])
    y = np.array([r["profitable"] for r in rows], dtype=float)
    zero = np.array([r["zero_drift_probability"] for r in rows])
    empirical = np.array([r["past_frequency_probability"] for r in rows])
    brier = (p-y)**2
    bins = []
    for i in range(10):
        mask = (p >= i/10) & ((p < (i+1)/10) if i < 9 else (p <= 1))
        if mask.any():
            bins.append({"lower": i/10, "upper": (i+1)/10, "n": int(mask.sum()),
                         "predicted": float(p[mask].mean()), "observed": float(y[mask].mean())})
    # Block bootstrap by entry month: overlapping contracts are not iid trials.
    blocks = {}
    for r, loss in zip(rows, brier):
        blocks.setdefault(r["entry"][:7], []).append(float(loss))
    ci = None
    if len(blocks) >= 6:
        values = list(blocks.values())
        rng = np.random.default_rng(47)
        means = [np.mean(np.concatenate([values[i] for i in rng.integers(
            0, len(values), len(values))])) for _ in range(500)]
        ci = np.quantile(means, [.025, .975]).tolist()
    return {
        "n": len(rows), "entry_months": len(blocks),
        "evidence": "descriptive only" if len(rows) >= minimum else "insufficient sample",
        "mean_predicted": float(p.mean()), "observed_profit_rate": float(y.mean()),
        "brier": float(brier.mean()), "brier_month_block_95_interval": ci,
        "log_loss": float(-np.mean(y*np.log(np.clip(p, 1e-6, 1-1e-6))
                                   +(1-y)*np.log(np.clip(1-p, 1e-6, 1-1e-6)))),
        "calibration_bins": bins,
        "expected_calibration_error": float(sum(
            b["n"]*abs(b["predicted"]-b["observed"]) for b in bins)/len(rows)),
        "brier_coin_flip": .25, "brier_zero_drift": float(np.mean((zero-y)**2)),
        "brier_past_frequency": float(np.mean((empirical-y)**2)),
        "brier_frictionless_live_probability": float(np.mean(
            (np.array([r["frictionless_live_probability"] for r in rows])-y)**2)),
        "daily_high95_coverage": float(np.mean([r["high_covered"] for r in rows])),
        "daily_low05_coverage": float(np.mean([r["low_covered"] for r in rows])),
        "mean_net_profit_per_contract": float(np.mean([r["net_profit"] for r in rows])),
        "mean_american_minus_european": float(np.mean([r["exercise_premium"] for r in rows])),
        "european_midpoint_mae": float(np.mean([abs(r["european_midpoint_error"]) for r in rows])),
        "american_midpoint_mae": float(np.mean([abs(r["american_midpoint_error"]) for r in rows])),
        "mean_dividend_price_effect": float(np.mean([r["dividend_price_effect"] for r in rows])),
    }


def run_study(history, quotes, sessions, config=StudyConfig()):
    """Forecast at each entry, score only complete later paths on supplied sessions.

    Session manifest is independent of option quote availability. Missing quotes
    therefore cannot shorten a horizon or silently remove a path's extreme.
    """
    if (not config.horizons or any(not isinstance(h, int) or h < 1 for h in config.horizons)
            or not 100 <= config.samples <= 10000 or not 1 <= config.max_dte <= 366
            or config.min_group_size < 1 or config.max_quote_age_seconds < 0
            or not np.isfinite([config.fee_per_contract, config.slippage_per_share]).all()
            or min(config.fee_per_contract, config.slippage_per_share) < 0):
        raise ValueError("Invalid study configuration.")
    history, quotes = prepare_data(history, quotes)
    session_frame = pd.DataFrame({"timestamp": list(sessions)})
    _timestamps(session_frame, ["timestamp"])
    sessions = pd.DatetimeIndex(session_frame.timestamp)
    if sessions.empty or sessions.has_duplicates or not sessions.is_monotonic_increasing:
        raise ValueError("Sessions must be a nonempty, sorted, unique manifest.")
    if not quotes.timestamp.isin(sessions).all():
        raise ValueError("Every quote cutoff must belong to the supplied session manifest.")
    rows, excluded = [], []
    lookup = quotes.set_index(["ticker", "timestamp"], drop=False)
    for _, entry in quotes.iterrows():
        def exclude(reason, horizon=None):
            excluded.append({"ticker": entry.ticker, "entry": entry.timestamp.isoformat(),
                             "horizon": horizon, "reason": reason})
        reason = _valid_snapshot(entry, config)
        dte = (entry.expiration-entry.timestamp.tz_convert("America/New_York").date()).days
        if reason or not 0 < dte <= config.max_dte:
            exclude(reason or "entry outside supported expiry range")
            continue
        fit = history[(history.timestamp <= entry.timestamp) &
                      (history.available_at <= entry.timestamp)].set_index("timestamp")
        if len(fit) < 253:
            exclude("less than 252 point-in-time returns")
            continue
        returns = np.diff(np.log(fit.Close.to_numpy()))
        sigma = float(returns.std(ddof=1)*np.sqrt(252))
        regime = "low (<50%)" if sigma < .5 else "medium (50–100%)" if sigma < 1 else "high (>=100%)"
        expiry_bucket = "1–30 days" if dte <= 30 else "31–90 days" if dte <= 90 else "91–180+ days"
        contract = entry.to_dict()
        contract["quote_time"] = entry.quote_time.isoformat()
        contract["spot_time"] = entry.spot_time.isoformat()
        try:
            forecast = project(fit, contract, entry.ask, entry.expiration,
                               now=entry.timestamp.to_pydatetime(), samples=config.samples,
                               rate=entry.rate, dividend=entry.dividend, return_paths=True)
            baseline = project(fit, contract, entry.ask, entry.expiration,
                               now=entry.timestamp.to_pydatetime(), samples=config.samples,
                               rate=entry.rate, dividend=entry.dividend, return_paths=True,
                               drift_override=0.)
            years = (pd.Timestamp(str(entry.expiration)+" 16:00",
                                  tz="America/New_York")-entry.timestamp).total_seconds()/(365.25*86400)
            european = float(price(entry.spot, entry.strike, years, entry.iv,
                                   entry.rate, entry.dividend, entry.type))
            american = american_price(entry.spot, entry.strike, years, entry.iv,
                                      entry.rate, entry.dividend, entry.type)
        except ValueError as exc:
            exclude(str(exc))
            continue
        dates = {pd.Timestamp(d).tz_convert("UTC"): i for i, d in enumerate(forecast["dates"])}
        later = sessions[sessions > entry.timestamp]
        half_spread = (entry.ask-entry.bid)/2
        cost = entry.ask + config.slippage_per_share + 2*config.fee_per_contract/100
        for horizon in config.horizons:
            path_dates = later[:horizon]
            if len(path_dates) != horizon or any(d not in dates for d in path_dates):
                exclude("horizon not observable before expiration/data end", horizon)
                continue
            path = []
            for date in path_dates:
                key = (entry.ticker, date)
                if key not in lookup.index or _valid_snapshot(lookup.loc[key], config):
                    break
                path.append(float(lookup.loc[key].bid))
            if len(path) != horizon:
                exclude("missing/stale daily path quote", horizon)
                continue
            ix = [dates[d] for d in path_dates]
            modeled_bids = np.maximum(forecast["paths"][:, ix]-half_spread, 0)-config.slippage_per_share
            zero_bids = np.maximum(baseline["paths"][:, ix[-1]]-half_spread, 0)-config.slippage_per_share
            actual = np.asarray(path)-config.slippage_per_share
            # Only outcomes already observable at entry may train this baseline.
            past = [r for r in rows if pd.Timestamp(r["exit"]) < entry.timestamp
                    and r["horizon_sessions"] == horizon and r["type"] == entry.type]
            frequency = (sum(r["profitable"] for r in past)+1)/(len(past)+2)
            low, high = (float(np.quantile(modeled_bids.min(axis=1), .05)),
                         float(np.quantile(modeled_bids.max(axis=1), .95)))
            midpoint = (entry.bid+entry.ask)/2
            rows.append({
                "ticker": entry.ticker, "source": str(entry.source),
                "entry": entry.timestamp.isoformat(), "exit": path_dates[-1].isoformat(),
                "fit_last_available_at": fit.available_at.max().isoformat(),
                "fit_returns": len(returns), "horizon_sessions": horizon, "type": entry.type,
                "expiration": str(entry.expiration), "expiry_bucket": expiry_bucket,
                "regime": regime, "realized_vol_at_entry": sigma,
                "probability": float(np.mean(modeled_bids[:, -1] > cost)),
                "frictionless_live_probability": float(np.mean(forecast["paths"][:, ix[-1]] > entry.ask)),
                "zero_drift_probability": float(np.mean(zero_bids > cost)),
                "past_frequency_probability": frequency, "past_frequency_n": len(past),
                "profitable": bool(actual[-1] > cost), "net_profit": float((actual[-1]-cost)*100),
                "predicted_low05": low, "predicted_high95": high,
                "observed_low": float(actual.min()), "observed_high": float(actual.max()),
                "low_covered": bool(actual.min() >= low), "high_covered": bool(actual.max() <= high),
                "exercise_premium": american-european,
                "european_midpoint_error": european-midpoint,
                "american_midpoint_error": american-midpoint,
                "dividend_price_effect": european-float(price(
                    entry.spot, entry.strike, years, entry.iv, entry.rate, 0., entry.type)),
            })
    grouped = {}
    for dimension in ["horizon_sessions", "expiry_bucket", "regime", "type", "expiration"]:
        grouped[dimension] = {
            str(key): _summary([r for r in rows if r[dimension] == key], config.min_group_size)
            for key in sorted({r[dimension] for r in rows})
        }
    # Cross strata detect failures masked by marginal summaries.
    for row in rows:
        key = f'{row["expiry_bucket"]} | {row["regime"]} | {row["horizon_sessions"]}'
        grouped.setdefault("expiry_regime_horizon", {}).setdefault(key, []).append(row)
    grouped["expiry_regime_horizon"] = {
        key: _summary(group, config.min_group_size)
        for key, group in grouped.get("expiry_regime_horizon", {}).items()
    }
    digest = hashlib.sha256((history.to_csv(index=False)+quotes.to_csv(index=False)
                             +str(list(sessions))).encode()).hexdigest()
    return {
        "version": 1, "status": "descriptive study; probabilities remain unvalidated" if rows
        else "no eligible historical outcomes; probabilities remain unvalidated",
        "claims_validated": False, "input_sha256": digest, "config": asdict(config),
        "input_quote_count": len(quotes), "overall": _summary(rows, config.min_group_size) if rows else None,
        "groups": grouped, "observations": rows, "exclusions": excluded,
        "limitations": [
            "User-supplied historical snapshots; provenance and full contract-universe coverage require independent audit.",
            "Entry ask and exit bid plus fees/slippage; quote liquidity and fills are not guaranteed.",
            "Future half-spread is held at entry half-spread for forecasts, not learned from future quotes.",
            "Daily path extremes use only supplied regular-close sessions, exclude entry, and are not intraday extremes.",
            "Overlapping trades are dependent; monthly block intervals are descriptive, not proof of calibration.",
            "CRR uses continuous yield; discrete ex-dividend exercise, assignments and corporate actions are not modeled.",
            "IV may be European-implied; American/midpoint residuals are diagnostics, not isolated causal pricing errors.",
            "No automatic strengthening of claims, even with large samples or favorable scores.",
        ],
    }


def report_json(report):
    return json.dumps(report, indent=2, allow_nan=False)
