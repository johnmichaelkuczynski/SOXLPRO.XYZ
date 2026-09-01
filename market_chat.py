"""Grounded conversational analysis for the SOXL chart."""

from __future__ import annotations

import json
import re
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from openai_client import DEFAULT_MODEL, get_openai_client


FORWARD_WINDOWS = (5, 21, 63)
CHART_MAPPING_EXPLANATION = (
    "**How the chart maps the lines:** displayed benchmark = actual benchmark "
    "close × (SOXL close on the first common date ÷ benchmark close on that "
    "date). Hover values remain the actual benchmark price. That rescaling is "
    "visual only; it is not a prediction."
)
ALLOWED_FOCUSES = {"signal", "correlation", "regime", "mapping", "general"}


def _return_pct(series: pd.Series, periods: int) -> float | None:
    clean = series.dropna()
    if len(clean) <= periods or clean.iloc[-periods - 1] <= 0:
        return None
    return float((clean.iloc[-1] / clean.iloc[-periods - 1] - 1) * 100)


def _number(value: float | None, digits: int = 2):
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), digits)


def _forward_stats(soxl_close: pd.Series, event_mask: pd.Series) -> dict:
    stats = {}
    for days in FORWARD_WINDOWS:
        forward = (soxl_close.shift(-days) / soxl_close - 1) * 100
        sample = forward[event_mask.reindex(forward.index, fill_value=False)].dropna()
        stats[f"{days}_trading_days"] = {
            "observations": int(len(sample)),
            "average_return_pct": _number(sample.mean()),
            "median_return_pct": _number(sample.median()),
            "positive_rate_pct": _number((sample > 0).mean() * 100, 1),
            "loss_5pct_or_worse_rate_pct": _number((sample <= -5).mean() * 100, 1),
            "gain_5pct_or_better_rate_pct": _number((sample >= 5).mean() * 100, 1),
        }
    return stats


def _benchmark_intelligence(
    soxl: pd.Series, benchmark: pd.Series, label: str
) -> dict:
    aligned = pd.concat(
        [soxl.rename("SOXL"), benchmark.rename(label)], axis=1, join="inner"
    ).dropna()
    if len(aligned) < 80:
        return {"error": "Insufficient overlapping history."}

    daily = aligned.pct_change(fill_method=None)
    bench_5d = aligned[label].pct_change(5, fill_method=None) * 100
    current_5d = bench_5d.iloc[-1]
    historical_5d = bench_5d.dropna()
    percentile = float((historical_5d <= current_5d).mean() * 100)
    low_q = historical_5d.quantile(max(0, percentile / 100 - 0.05))
    high_q = historical_5d.quantile(min(1, percentile / 100 + 0.05))
    similar_mask = bench_5d.between(low_q, high_q)

    result = {
        "history": {
            "first_common_date": aligned.index[0].strftime("%Y-%m-%d"),
            "last_common_date": aligned.index[-1].strftime("%Y-%m-%d"),
            "observations": int(len(aligned)),
        },
        "current": {
            "price": _number(aligned[label].iloc[-1]),
            "return_1d_pct": _number(_return_pct(aligned[label], 1)),
            "return_5d_pct": _number(current_5d),
            "return_21d_pct": _number(_return_pct(aligned[label], 21)),
            "five_day_return_percentile": _number(percentile, 1),
        },
        "daily_return_correlation": {
            "21_days": _number(daily["SOXL"].tail(21).corr(daily[label].tail(21)), 3),
            "63_days": _number(daily["SOXL"].tail(63).corr(daily[label].tail(63)), 3),
            "252_days": _number(daily["SOXL"].tail(252).corr(daily[label].tail(252)), 3),
            "full_history": _number(daily["SOXL"].corr(daily[label]), 3),
        },
        "similar_to_current_5d_move": {
            "benchmark_5d_return_band_pct": [_number(low_q), _number(high_q)],
            "soxl_forward_results": _forward_stats(aligned["SOXL"], similar_mask),
        },
    }

    if label == "VIX":
        vix = aligned[label]
        current = float(vix.iloc[-1])
        bins = [
            ("below_15", vix < 15),
            ("15_to_20", (vix >= 15) & (vix < 20)),
            ("20_to_25", (vix >= 20) & (vix < 25)),
            ("25_to_30", (vix >= 25) & (vix < 30)),
            ("30_or_higher", vix >= 30),
        ]
        current_regime = next(name for name, mask in bins if bool(mask.iloc[-1]))
        result["vix_level_analysis"] = {
            "current_level": _number(current),
            "current_regime": current_regime,
            "soxl_forward_results_by_vix_regime": {
                name: _forward_stats(aligned["SOXL"], mask) for name, mask in bins
            },
        }
        vix_5d = vix.pct_change(5, fill_method=None) * 100
        result["vix_signal_tests"] = {
            "after_5d_spike_of_20pct_or_more": _forward_stats(
                aligned["SOXL"], vix_5d >= 20
            ),
            "after_5d_drop_of_15pct_or_more": _forward_stats(
                aligned["SOXL"], vix_5d <= -15
            ),
            "vix_above_30_and_falling_today": _forward_stats(
                aligned["SOXL"], (vix >= 30) & (vix.diff() < 0)
            ),
        }

    return result


def build_market_intelligence(
    soxl_data: pd.DataFrame,
    benchmarks: Mapping[str, pd.DataFrame],
    current_soxl_price: float,
    quote_context: Mapping | None = None,
) -> dict:
    soxl = soxl_data["Close"].dropna().sort_index()
    quote_context = dict(quote_context or {})
    context = {
        "as_of": soxl.index[-1].strftime("%Y-%m-%d"),
        "soxl": {
            "displayed_price": _number(current_soxl_price),
            "displayed_price_state": quote_context.get("state", "daily close"),
            "displayed_price_is_extended_hours": bool(
                quote_context.get("extended", False)
            ),
            "displayed_price_retrieved_at": quote_context.get("retrieved_at"),
            "last_daily_close": _number(soxl.iloc[-1]),
            "last_daily_close_date": soxl.index[-1].strftime("%Y-%m-%d"),
            "return_1d_pct": _number(_return_pct(soxl, 1)),
            "return_5d_pct": _number(_return_pct(soxl, 5)),
            "return_21d_pct": _number(_return_pct(soxl, 21)),
            "return_63d_pct": _number(_return_pct(soxl, 63)),
        },
        "chart_mapping": (
            "Each benchmark line is normalized onto SOXL's price scale at the "
            "first common date: displayed benchmark = actual benchmark close × "
            "(SOXL close on first common date / benchmark close on first common "
            "date). Hover values use the benchmark's actual unscaled price. This "
            "is a visual comparison, not a predictive or causal function."
        ),
        "analysis_basis": (
            "All correlations and forward signal tests use aligned daily closes "
            "through each pair's last common date. The displayed SOXL quote may "
            "be newer and is never mixed into those historical calculations."
        ),
        "benchmarks": {},
    }
    for label, frame in benchmarks.items():
        if frame is not None and not frame.empty and "Close" in frame:
            context["benchmarks"][label] = _benchmark_intelligence(
                soxl, frame["Close"].dropna().sort_index(), label
            )
    return context


def _fmt(value, suffix="", signed=False) -> str:
    if value is None:
        return "not available"
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value:,.2f}{suffix}"


def _evidence_catalog(intelligence: dict) -> dict[str, str]:
    catalog = {}
    soxl = intelligence["soxl"]
    catalog["SOXL.daily_close"] = (
        f"SOXL's daily close was ${_fmt(soxl['last_daily_close'])} on "
        f"{soxl['last_daily_close_date']}."
    )
    if soxl["displayed_price"] != soxl["last_daily_close"]:
        catalog["SOXL.displayed_quote"] = (
            f"The displayed SOXL quote was ${_fmt(soxl['displayed_price'])} "
            f"({soxl['displayed_price_state']}); relationship tests still use "
            f"the ${_fmt(soxl['last_daily_close'])} daily close from "
            f"{soxl['last_daily_close_date']}."
        )

    for label, info in intelligence["benchmarks"].items():
        if "error" in info:
            continue
        current = info["current"]
        last_date = info["history"]["last_common_date"]
        catalog[f"{label}.current"] = (
            f"{label}'s latest aligned daily close was "
            f"{'$' if label != 'VIX' else ''}{_fmt(current['price'])} on "
            f"{last_date}; its five-day move was "
            f"{_fmt(current['return_5d_pct'], '%', signed=True)} at the "
            f"{_fmt(current['five_day_return_percentile'], '%')} historical percentile."
        )
        for window, corr in info["daily_return_correlation"].items():
            catalog[f"{label}.correlation.{window}"] = (
                f"SOXL/{label} daily-return correlation over {window.replace('_', ' ')} "
                f"was {_fmt(corr)}. Correlation is contemporaneous, not a forward signal."
            )
        for horizon, stats in info["similar_to_current_5d_move"][
            "soxl_forward_results"
        ].items():
            days = horizon.split("_")[0]
            catalog[f"{label}.similar_move.forward_{days}d"] = (
                f"After {label} five-day moves similar to today's, SOXL was higher "
                f"{_fmt(stats['positive_rate_pct'], '%')} of the time after {days} "
                f"trading days (n={stats['observations']}), with average "
                f"{_fmt(stats['average_return_pct'], '%', signed=True)} and median "
                f"{_fmt(stats['median_return_pct'], '%', signed=True)} returns."
            )

        if label == "VIX" and "vix_level_analysis" in info:
            vix_info = info["vix_level_analysis"]
            regime = vix_info["current_regime"]
            for horizon, stats in vix_info["soxl_forward_results_by_vix_regime"][
                regime
            ].items():
                days = horizon.split("_")[0]
                catalog[f"VIX.current_regime.forward_{days}d"] = (
                    f"With VIX in today's {regime.replace('_', ' ')} regime, SOXL "
                    f"was higher {_fmt(stats['positive_rate_pct'], '%')} of the time "
                    f"after {days} trading days (n={stats['observations']}), with "
                    f"average {_fmt(stats['average_return_pct'], '%', signed=True)} "
                    f"and median {_fmt(stats['median_return_pct'], '%', signed=True)} returns."
                )
            for signal, windows in info["vix_signal_tests"].items():
                for horizon, stats in windows.items():
                    days = horizon.split("_")[0]
                    catalog[f"VIX.{signal}.forward_{days}d"] = (
                        f"For {signal.replace('_', ' ')}, SOXL was higher "
                        f"{_fmt(stats['positive_rate_pct'], '%')} of the time after "
                        f"{days} trading days (n={stats['observations']}), with average "
                        f"{_fmt(stats['average_return_pct'], '%', signed=True)} and median "
                        f"{_fmt(stats['median_return_pct'], '%', signed=True)} returns."
                    )
    return catalog


def _fallback_evidence_ids(catalog: Mapping[str, str], benchmarks: Mapping) -> list[str]:
    preferred = []
    for label in benchmarks:
        for suffix in (
            "similar_move.forward_21d",
            "similar_move.forward_5d",
            "correlation.63_days",
            "current",
        ):
            key = f"{label}.{suffix}"
            if key in catalog:
                preferred.append(key)
    return preferred[:5] or list(catalog)[:5]


def _interpretation_from_evidence(
    focus: str, evidence_statements: Sequence[str]
) -> str:
    """Return only allowlisted, non-prescriptive explanatory language."""
    if focus == "mapping":
        return (
            "The chart puts differently priced assets onto one visual scale so "
            "their paths are easier to compare. It does not imply that one line "
            "is mechanically converted into the other."
        )
    if focus == "correlation":
        return (
            "The selected evidence describes how the assets moved at the same "
            "time. That can clarify their relationship, but it is not by itself "
            "a forecast of what SOXL does next."
        )

    positive_rates = []
    for statement in evidence_statements:
        match = re.search(r"SOXL was higher ([\d.]+)%", statement)
        if match:
            positive_rates.append(float(match.group(1)))

    if focus in {"signal", "regime"} and positive_rates:
        average_rate = sum(positive_rates) / len(positive_rates)
        if average_rate >= 57:
            return (
                "The selected historical evidence leans modestly positive for "
                "SOXL, but it is not strong enough to be a stand-alone timing "
                "rule. The forward outcomes below show both the tendency and "
                "the uncertainty around it."
            )
        if average_rate <= 43:
            return (
                "The selected historical evidence leans modestly negative for "
                "SOXL, but it is not strong enough to be a stand-alone timing "
                "rule. The forward outcomes below show both the tendency and "
                "the uncertainty around it."
            )
        return (
            "The selected forward evidence is mixed and does not show a clear "
            "historical timing edge for SOXL. Treat the benchmark as context "
            "rather than a mechanical signal."
        )
    if focus == "regime":
        return (
            "The current benchmark regime can provide market context, but the "
            "available validated evidence does not support a directional claim."
        )
    return (
        "The chart can reveal a relationship worth researching, but it does not "
        "create a mechanical trading rule. Same-day correlation and forward "
        "predictive evidence are different, so the historical outcomes below "
        "should be treated as context rather than certainty."
    )


def answer_market_question(
    messages: Sequence[dict],
    soxl_data: pd.DataFrame,
    benchmarks: Mapping[str, pd.DataFrame],
    current_soxl_price: float,
    quote_context: Mapping | None = None,
) -> str:
    intelligence = build_market_intelligence(
        soxl_data, benchmarks, current_soxl_price, quote_context
    )
    catalog = _evidence_catalog(intelligence)
    system = """Classify a user's SOXL chart question and select supporting evidence.
Return a JSON object with exactly two keys:
1. focus: exactly one of signal, correlation, regime, mapping, or general.
2. evidence_ids: an array of at most six exact IDs selected from AVAILABLE_EVIDENCE.
Choose only evidence that directly supports the user's latest question. Do not
create IDs. Return no explanation, advice, price, probability, or other prose."""
    conversation = [
        {"role": m["role"], "content": str(m["content"])}
        for m in messages[-10:]
        if m.get("role") in {"user", "assistant"}
    ]
    user_payload = {
        "conversation": conversation,
        "available_evidence": catalog,
    }
    response = get_openai_client().chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(user_payload, separators=(",", ":")),
            },
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=2200,
    )
    parsed = json.loads(response.choices[0].message.content or "{}")
    focus = str(parsed.get("focus", "general")).strip().lower()
    if focus not in ALLOWED_FOCUSES:
        focus = "general"
    requested_ids = parsed.get("evidence_ids", [])
    evidence_ids = [
        item for item in requested_ids if isinstance(item, str) and item in catalog
    ][:6]
    if not evidence_ids:
        evidence_ids = _fallback_evidence_ids(catalog, benchmarks)

    evidence_statements = [catalog[item] for item in evidence_ids]
    explanation = _interpretation_from_evidence(focus, evidence_statements)
    parts = [explanation, CHART_MAPPING_EXPLANATION]
    if evidence_ids:
        parts.append(
            "**Evidence calculated by the app:**\n"
            + "\n".join(f"- {statement}" for statement in evidence_statements)
        )
    parts.append(
        f"**Data basis:** {intelligence['analysis_basis']} "
        f"Daily-close data is current through {intelligence['as_of']}."
    )
    parts.append(
        "_Risk note: SOXL is a leveraged ETF. Historical relationships can break "
        "down quickly, so this is research context—not personalized investment advice._"
    )
    return "\n\n".join(parts)