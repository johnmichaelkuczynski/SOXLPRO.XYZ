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
APP_KNOWLEDGE = """
SOXL Pro is a public research application centered on SOXL, a leveraged
semiconductor ETF. The assistant may discuss the whole application:

- Chart & Probabilities: SOXL history, normalized overlays for QQQ, TQQQ, TLT,
  XLU, VIX, SOX, GUSH, and BTC; drawn trend lines; selected-period analysis;
  SOXL-history and benchmark-history probability studies.
- Vol Surface: current SOXL option-chain implied volatility across strike and
  expiration, with liquidity/no-arbitrage quality filters, fitted smiles, local
  outlier filtering, and model-discrepancy tables. A discrepancy is not a
  guaranteed trade.
- Call Risk/Reward: ask-price purchase cost, expiration scenario payoff,
  break-even, maximum loss, risk-neutral probability estimates, theta,
  liquidity, and a composite Risk Score. Missing or implausible IV suppresses
  model probabilities but not deterministic payoff scenarios.
- SOXL-QQQ Dislocation: rolling beta, residual return, z-scores, historical
  mean-reversion events, and clearly labeled relative-value verdicts.
- Strategy Builder: conversational portfolio context plus historical
  probability tables to create a structured SOXL entry framework.
- Backtest: allocation engine, period analysis, probability engine, volatility
  regimes, dislocation, strategy-builder, limited volatility-surface, and
  custom-strategy backtests with risk-adjusted metrics and downloadable reports.
- Diagnostic: system checks, synthetic-user checks, quality control, and
  backtest sweeps.

Explain where a user can find a tool, how it works, what its output means, how
two tools differ, and what its limitations are. Do not claim access to news,
fundamentals, account holdings, or data that is not present in the supplied
knowledge and evidence.
""".strip()

PRODUCT_EVIDENCE = {
    "APP.call_payoff": (
        "Call Risk/Reward uses purchase cost = ask × 100 shares, break-even = "
        "strike + ask, and expiration P/L = [max(SOXL at expiration − strike, 0) "
        "− ask] × 100."
    ),
    "APP.risk_score": (
        "The Call Risk Score is 70% modeled probability of loss, 20% theta burn "
        "as a percentage of premium, and 10% liquidity; higher means more model risk."
    ),
    "APP.dislocation": (
        "SOXL-QQQ Dislocation compares SOXL returns with rolling-beta-implied QQQ "
        "returns, then standardizes cumulative residuals into z-scores and checks "
        "historical mean reversion."
    ),
    "APP.vol_surface": (
        "Vol Surface organizes current SOXL option-chain implied volatility across "
        "strike and expiration, applies liquidity and no-arbitrage quality filters, "
        "fits volatility smiles, and flags contracts whose market IV differs from "
        "the fitted surface."
    ),
    "APP.probability_engine": (
        "The Probability Engine measures how often SOXL historically reached a "
        "chosen move over a chosen horizon; Benchmark History instead conditions "
        "SOXL's later outcomes on historically similar benchmark behavior."
    ),
    "APP.strategy_builder": (
        "Strategy Builder combines the user's stated goals and risk context with "
        "historical SOXL probability tables to create a structured entry framework."
    ),
    "APP.diagnostic": (
        "Diagnostic contains system checks, synthetic-user checks, quality-control "
        "checks, and backtest sweeps so operators can inspect whether data, AI, and "
        "analytical workflows are functioning."
    ),
    "APP.backtest_data": (
        "Backtests include allocation, period, probability, volatility-regime, "
        "dislocation, strategy, volatility-surface, and custom-strategy studies; "
        "their displayed methodology and date limits define what each result covers."
    ),
}


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


def _safe_fallback(
    focus: str, evidence_statements: Sequence[str], conversation_text: str = ""
) -> str:
    """Return an allowlisted fallback if generated prose fails validation."""
    lowered = conversation_text.lower()
    asks_calls = any(
        term in lowered
        for term in ("call risk", "risk score", "call option", "break-even", "theta")
    )
    asks_surface = any(
        term in lowered
        for term in ("vol surface", "volatility surface", "implied volatility", "skew")
    )
    if asks_calls and asks_surface:
        return (
            "Call Risk/Reward analyzes the economics and modeled risk of individual "
            "call contracts: what the buyer pays, where the contract breaks even, "
            "how expiration scenarios change the payoff, and how probability, time "
            "decay, and liquidity affect the Risk Score. Vol Surface answers a "
            "different question. It compares implied volatility across strikes and "
            "expirations, fits the overall smile or skew, and highlights contracts "
            "whose volatility differs from nearby contracts. Use Call Risk/Reward "
            "to inspect a contract's payoff trade-off; use Vol Surface to inspect "
            "how the options market is pricing volatility across the chain."
        )
    if asks_calls:
        return (
            "The Call Risk Score summarizes three pressures on a call contract: the "
            "model-estimated chance of finishing below break-even, current time-decay "
            "burn relative to the premium, and trading liquidity. Higher scores mean "
            "more modeled risk under those assumptions. You can find it in the Call "
            "Risk/Reward tab beside each contract's payoff scenarios, break-even, "
            "theta, and liquidity details."
        )
    if asks_surface:
        return (
            "The Vol Surface shows how the options market prices implied volatility "
            "across strikes and expiration dates. It fits the broader volatility "
            "shape, filters low-quality observations, and highlights contracts whose "
            "market volatility differs from nearby contracts. It is useful for "
            "examining relative option pricing, not for guaranteeing that a flagged "
            "contract is mispriced."
        )
    if "dislocation" in lowered:
        return (
            "SOXL-QQQ Dislocation asks whether SOXL has moved unusually far from "
            "what its recent relationship with QQQ would imply. It estimates rolling "
            "beta, measures the residual move, standardizes it, and compares similar "
            "historical episodes for mean reversion."
        )
    asks_strategy = any(
        term in lowered
        for term in ("strategy builder", "entry strategy", "strategy assistant")
    )
    asks_backtest = any(
        term in lowered for term in ("backtest", "historical test", "test a strategy")
    )
    if asks_strategy and asks_backtest:
        return (
            "Strategy Builder and Backtest serve different roles. Strategy Builder "
            "uses the user's goals, available cash, risk tolerance, and historical "
            "probabilities to draft a structured entry framework. Backtest then "
            "examines defined rules against historical data and reports how they "
            "would have behaved, including risk and drawdown measures. Use Strategy "
            "Builder to formulate an approach and Backtest to challenge its rules "
            "before treating the framework as actionable."
        )
    if asks_strategy:
        return (
            "Strategy Builder is the app's conversational planning tool. It combines "
            "the user's portfolio context, available cash, risk tolerance, and goals "
            "with historical SOXL probability tables, then produces a structured "
            "entry framework. It is a planning aid rather than a guarantee or a "
            "substitute for testing the rules."
        )
    if any(
        term in lowered
        for term in (
            "diagnostic",
            "system check",
            "synthetic user",
            "quality control",
            "backtest sweep",
        )
    ):
        return (
            "Diagnostic is the app's inspection area. System Check examines core "
            "data and AI dependencies, Synthetic User exercises a realistic strategy "
            "conversation, Quality Control reviews generated output, and Backtest "
            "Sweep checks analytical behavior across multiple configurations. It "
            "helps diagnose whether the application is functioning; it does not "
            "produce a market forecast."
        )
    if asks_backtest:
        return (
            "The Backtest area lets you test the app's analytical ideas against "
            "historical data rather than accepting a current signal at face value. "
            "It includes allocation, probability, volatility-regime, dislocation, "
            "strategy, volatility-surface, and custom-strategy studies with risk "
            "metrics and methodology notes."
        )
    if "probability" in lowered:
        return (
            "The Probability Engine counts comparable historical outcomes for a "
            "chosen SOXL move and time horizon. Its benchmark mode asks a different "
            "question: after benchmark behavior similar to the selected setup, what "
            "did SOXL do next? Results are historical frequencies, not forecasts."
        )
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
        "I can explain any SOXL Pro tool, compare its outputs, and use the app's "
        "validated market evidence to examine a question. Ask about the chart, "
        "probabilities, options, volatility surface, dislocation, strategy tools, "
        "backtests, or diagnostics."
    )


def _deterministic_product_evidence(conversation_text: str) -> list[str]:
    lowered = conversation_text.lower()
    selected = []
    keyword_map = (
        (
            ("call risk", "risk score", "call option", "break-even", "theta"),
            ("APP.risk_score", "APP.call_payoff"),
        ),
        (
            ("vol surface", "volatility surface", "implied volatility", "skew"),
            ("APP.vol_surface",),
        ),
        (("dislocation", "relative to qqq", "mean reversion"), ("APP.dislocation",)),
        (("backtest", "historical test"), ("APP.backtest_data",)),
        (("probability engine", "historical probability"), ("APP.probability_engine",)),
        (("strategy builder", "entry strategy"), ("APP.strategy_builder",)),
        (
            (
                "diagnostic",
                "system check",
                "synthetic user",
                "quality control",
                "backtest sweep",
            ),
            ("APP.diagnostic",),
        ),
    )
    for terms, evidence_ids in keyword_map:
        if any(term in lowered for term in terms):
            selected.extend(evidence_ids)
    return list(dict.fromkeys(selected))


def _needs_mapping(question: str, requested: bool) -> bool:
    terms = (
        "map",
        "mapping",
        "normaliz",
        "same scale",
        "function",
        "overlay",
        "what do the lines",
        "what do these lines",
        "what does the line",
        "chart line",
    )
    lowered = question.lower()
    explicit_chart_context = any(
        term in lowered for term in ("chart", "line", "overlay", "benchmark")
    )
    return any(term in lowered for term in terms) or (
        requested and explicit_chart_context
    )


def _validate_generated_answer(
    client, question: str, answer: str, approved_evidence: Sequence[str]
) -> bool:
    """Semantic guard for natural prose; fail closed on any validator problem."""
    if not answer or re.search(r"[\d$%]", answer):
        return False
    validation = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Audit an answer from a financial research app. Return JSON "
                    "with safe=true only if it contains no deterministic instruction "
                    "to buy, sell, enter, exit, accumulate, short, or open a position; "
                    "no guaranteed outcome; no unsupported price, probability, date, "
                    "quantity, news, or fabricated app capability; and no claim that "
                    "correlation proves causation. Educational explanations of what "
                    "an app tool measures are allowed. Keys: safe (boolean), reason "
                    "(short string)."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "answer": answer,
                        "approved_app_knowledge": APP_KNOWLEDGE,
                        "approved_evidence": list(approved_evidence),
                    }
                ),
            },
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=1200,
    )
    result = json.loads(validation.choices[0].message.content or "{}")
    return result.get("safe") is True


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
    catalog.update(PRODUCT_EVIDENCE)
    system = """You are the conversational intelligence inside SOXL Pro. Users
may talk with you naturally about the entire app, not only the chart. Answer
their latest question directly, organically, and in plain English. Use prior
conversation for context.

Return JSON with exactly four keys:
- answer: natural explanatory prose with no digits, dollar signs, percent signs,
  dates, sample sizes, or unsupported numerical claims. Do not give deterministic
  trading instructions or guarantees. Numerical evidence is rendered separately.
- focus: one of signal, correlation, regime, mapping, or general.
- evidence_ids: at most six exact IDs from AVAILABLE_EVIDENCE that directly
  support the answer. Do not invent IDs.
- show_mapping: boolean, true when explaining normalized chart lines.

You may explain navigation, methods, relationships, limitations, or compare
features using APPROVED_APP_KNOWLEDGE. Never pretend the app has data or tools
outside that knowledge. For market conclusions, distinguish correlation from
forward evidence and treat findings as research context."""
    conversation = [
        {"role": m["role"], "content": str(m["content"])}
        for m in messages[-10:]
        if m.get("role") in {"user", "assistant"}
    ]
    conversation_text = " ".join(
        message["content"] for message in conversation if message["role"] == "user"
    )
    user_payload = {
        "conversation": conversation,
        "approved_app_knowledge": APP_KNOWLEDGE,
        "available_evidence": catalog,
    }
    client = get_openai_client()
    response = client.chat.completions.create(
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
    model_evidence_ids = [
        item for item in requested_ids if isinstance(item, str) and item in catalog
    ][:6]
    evidence_ids = list(
        dict.fromkeys(
            _deterministic_product_evidence(conversation_text) + model_evidence_ids
        )
    )[:6]
    latest_question = conversation[-1]["content"] if conversation else ""
    asks_for_market_evidence = any(
        term in latest_question.lower()
        for term in (
            "signal",
            "predict",
            "probability",
            "chance",
            "correlation",
            "return",
            "buy",
            "sell",
            "right now",
            "today",
        )
    )
    if not evidence_ids and asks_for_market_evidence:
        evidence_ids = _fallback_evidence_ids(catalog, benchmarks)

    evidence_statements = [catalog[item] for item in evidence_ids]
    generated_answer = str(parsed.get("answer", "")).strip()
    try:
        answer_is_safe = _validate_generated_answer(
            client,
            latest_question,
            generated_answer,
            [catalog[item] for item in evidence_ids],
        )
    except Exception:
        answer_is_safe = False
    explanation = (
        generated_answer
        if answer_is_safe
        else _safe_fallback(focus, evidence_statements, conversation_text)
    )
    parts = [explanation]
    if _needs_mapping(latest_question, bool(parsed.get("show_mapping", False))):
        parts.append(CHART_MAPPING_EXPLANATION)
    if evidence_ids:
        parts.append(
            "**Evidence calculated by the app:**\n"
            + "\n".join(f"- {statement}" for statement in evidence_statements)
        )
    has_market_evidence = any(not item.startswith("APP.") for item in evidence_ids)
    if has_market_evidence:
        parts.append(
            f"**Data basis:** {intelligence['analysis_basis']} "
            f"Daily-close data is current through {intelligence['as_of']}."
        )
    if asks_for_market_evidence:
        parts.append(
            "_Risk note: SOXL is a leveraged ETF. Historical relationships can "
            "break down quickly, so this is research context—not personalized "
            "investment advice._"
        )
    return "\n\n".join(parts)