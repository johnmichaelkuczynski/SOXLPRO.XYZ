"""Synthetic fixtures validate mechanics only, not financial accuracy."""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from options_projection_model import price
from options_validation import StudyConfig, american_price, report_json, run_study


CONFIG = StudyConfig(horizons=(2, 5), samples=100)


def inputs(kind="call"):
    sessions = pd.date_range("2025-02-03 16:00", periods=8, freq="B",
                             tz="America/New_York")
    historical = pd.date_range(end=sessions[0]-pd.Timedelta(days=3), periods=300,
                               freq="B")
    history = pd.DataFrame({
        "timestamp": historical, "available_at": historical,
        "Close": 50*np.exp(np.cumsum(np.random.default_rng(2).normal(0, .03, 300))),
    })
    rows = []
    for j, t in enumerate(sessions):
        rows.append(dict(
            ticker="historical-test-only", timestamp=t.isoformat(),
            quote_time=t.isoformat(), spot_time=t.isoformat(), iv_time=t.isoformat(),
            rate_time=t.isoformat(), dividend_time=t.isoformat(), expiration="2025-02-21",
            type=kind, strike=50, spot=50+j, iv=.7, bid=2+j*.2, ask=2.2+j*.2,
            rate=.04, dividend=.01, multiplier=100, source="SYNTHETIC UNIT TEST ONLY"))
    return history, pd.DataFrame(rows), sessions


def test_execution_calibration_and_report():
    report = run_study(*inputs(), CONFIG)
    row = report["observations"][0]
    assert row["net_profit"] == pytest.approx((2.4-.01-2.2-.01)*100-1.3)
    assert row["profitable"] is True
    assert row["observed_low"] == pytest.approx(2.2-.01)
    assert row["observed_high"] == pytest.approx(2.4-.01)
    summary = report["overall"]
    assert summary["n"] == 9  # six 2-day and three 5-day outcomes
    assert summary["brier"] == pytest.approx(np.mean([
        (r["probability"]-r["profitable"])**2 for r in report["observations"]]))
    assert sum(b["n"] for b in summary["calibration_bins"]) == summary["n"]
    assert summary["evidence"] == "insufficient sample"
    assert summary["brier_month_block_95_interval"] is None
    assert report["groups"]["expiry_regime_horizon"]
    assert report["claims_validated"] is False
    assert "NaN" not in report_json(report)
    assert report == run_study(*inputs(), CONFIG)


def test_no_future_history_or_availability_leakage():
    history, quotes, sessions = inputs()
    original = run_study(history, quotes, sessions, CONFIG)["observations"][0]
    # Both future observations and historically dated but not-yet-available
    # prices are prohibited from entering the first forecast.
    extra = pd.DataFrame([
        dict(timestamp=sessions[-1], available_at=sessions[-1], Close=999999),
        dict(timestamp=history.timestamp.iloc[0]-pd.Timedelta(days=1),
             available_at=sessions[-1], Close=.0001),
    ])
    changed = run_study(pd.concat([history, extra]), quotes, sessions, CONFIG)["observations"][0]
    assert original["probability"] == changed["probability"]
    assert original["predicted_high95"] == changed["predicted_high95"]
    assert original["fit_returns"] == changed["fit_returns"]
    assert pd.Timestamp(changed["fit_last_available_at"]) <= pd.Timestamp(changed["entry"])


def test_future_quote_values_cannot_change_forecasts():
    history, quotes, sessions = inputs()
    original = run_study(history, quotes, sessions, CONFIG)["observations"][0]
    quotes.loc[1:, ["bid", "ask", "iv", "spot"]] *= 2
    changed = run_study(history, quotes, sessions, CONFIG)["observations"][0]
    for field in ["probability", "zero_drift_probability", "predicted_low05",
                  "predicted_high95", "past_frequency_probability", "exercise_premium"]:
        assert changed[field] == original[field]
    assert changed["net_profit"] != original["net_profit"]


def test_missing_path_not_silently_shortened():
    history, quotes, sessions = inputs()
    report = run_study(history, quotes.drop(index=1), sessions, CONFIG)
    entry = sessions[0].tz_convert("UTC").isoformat()
    assert not any(r["entry"] == entry for r in report["observations"])
    assert any(r["entry"] == entry and r["reason"] == "missing/stale daily path quote"
               for r in report["exclusions"])


@pytest.mark.parametrize("field", ["quote_time", "spot_time", "iv_time", "rate_time", "dividend_time"])
def test_future_inputs_excluded(field):
    history, quotes, sessions = inputs()
    quotes.loc[0, field] = (sessions[0]+pd.Timedelta(minutes=1)).isoformat()
    report = run_study(history, quotes, sessions, CONFIG)
    assert not any(r["entry"] == sessions[0].tz_convert("UTC").isoformat()
                   for r in report["observations"])
    assert report["exclusions"][0]["reason"].startswith("future")


@pytest.mark.parametrize("change", [
    {"bid": -1}, {"ask": .1}, {"multiplier": 10}, {"iv": np.nan},
    {"type": "straddle"}, {"source": ""}, {"timestamp": "2025-02-03 16:00"},
])
def test_bad_data_rejected(change):
    history, quotes, sessions = inputs()
    for key, value in change.items():
        quotes.loc[0, key] = value
    with pytest.raises(ValueError):
        run_study(history, quotes, sessions, CONFIG)


def test_duplicates_calendar_and_empty_inputs_rejected():
    history, quotes, sessions = inputs()
    with pytest.raises(ValueError, match="Duplicate"):
        run_study(history, pd.concat([quotes, quotes.iloc[:1]]), sessions, CONFIG)
    with pytest.raises(ValueError, match="manifest"):
        run_study(history, quotes, sessions[1:], CONFIG)
    with pytest.raises(ValueError, match="required"):
        run_study(history, quotes.iloc[:0], sessions, CONFIG)
    with pytest.raises(ValueError, match="configuration"):
        run_study(history, quotes, sessions, replace(CONFIG, fee_per_contract=-1))


def test_frequency_baseline_only_matured_outcomes():
    report = run_study(*inputs(), CONFIG)
    rows = report["observations"]
    for row in rows:
        past = [r for r in rows if pd.Timestamp(r["exit"]) < pd.Timestamp(row["entry"])
                and r["horizon_sessions"] == row["horizon_sessions"] and r["type"] == row["type"]]
        assert row["past_frequency_n"] == len(past)
        assert row["past_frequency_probability"] == (sum(r["profitable"] for r in past)+1)/(len(past)+2)


def test_cost_increase_reduces_profit_and_probability():
    cheap = run_study(*inputs(), replace(CONFIG, fee_per_contract=0, slippage_per_share=0))
    costly = run_study(*inputs(), replace(CONFIG, fee_per_contract=2, slippage_per_share=.2))
    for a, b in zip(cheap["observations"], costly["observations"]):
        assert a["net_profit"] > b["net_profit"]
        assert a["probability"] >= b["probability"]


def test_puts_and_expiration_boundaries():
    history, quotes, sessions = inputs("put")
    quotes["expiration"] = "2025-02-05"
    report = run_study(history, quotes, sessions, CONFIG)
    assert len(report["observations"]) == 1
    assert report["observations"][0]["exit"] == sessions[2].tz_convert("UTC").isoformat()
    assert report["groups"]["type"]["put"]["n"] == 1


def test_american_exercise_and_dividend_sensitivity():
    euro = float(price(100, 100, 1, .2, .05, 0, "call"))
    assert american_price(100, 100, 1, .2, .05, 0, "call", steps=1000) == pytest.approx(euro, abs=.01)
    euro_put = float(price(50, 100, 1, .2, .1, 0, "put"))
    assert american_price(50, 100, 1, .2, .1, 0, "put") >= 50 > euro_put
    with_dividend = american_price(120, 100, .5, .2, .02, .15, "call")
    assert with_dividend >= 20
    assert with_dividend > float(price(120, 100, .5, .2, .02, .15, "call"))
    assert american_price(100, 110, 0, .2, .04, 0, "put") == 10
