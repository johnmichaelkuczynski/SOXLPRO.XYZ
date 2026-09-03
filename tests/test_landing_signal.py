import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from landing_signal import (
    TIMEFRAMES,
    TIMEFRAME_WEIGHTS,
    completed_close_history,
    composite_signal,
    compute_timeframe_readings,
    condition_from_percentile,
    price_range_percentile,
    signal_from_percentile,
)
from backtest_engine import (
    build_signal_reliability_report_rows,
    classify_market_regimes,
    summarize_signal_backtest,
    walk_forward_signal_backtest,
)


def _history(periods=4200):
    dates = pd.bdate_range("2010-01-04", periods=periods)
    closes = np.linspace(10.0, 110.0, periods)
    return pd.DataFrame({"Close": closes}, index=dates)


class LandingSignalTests(unittest.TestCase):
    def test_formula_uses_current_min_and_max(self):
        percentile, current, low, high = price_range_percentile([10, 30, 50])
        self.assertEqual(percentile, 100.0)
        self.assertEqual((current, low, high), (50.0, 10.0, 50.0))
        percentile, *_ = price_range_percentile([10, 30, 20])
        self.assertEqual(percentile, 50.0)

    def test_flat_or_single_price_range_is_unavailable(self):
        for values in ([10], [10, 10, 10]):
            percentile, *_ = price_range_percentile(values)
            self.assertTrue(np.isnan(percentile))

    def test_condition_boundaries(self):
        self.assertEqual(condition_from_percentile(19.99), "Oversold")
        self.assertEqual(condition_from_percentile(20), "Neutral")
        self.assertEqual(condition_from_percentile(80), "Neutral")
        self.assertEqual(condition_from_percentile(80.01), "Overbought")

    def test_signal_boundaries_match_requested_ranges(self):
        expected = {
            0: "STRONG BUY",
            14.99: "STRONG BUY",
            15: "BUY",
            34.99: "BUY",
            35: "DO NOTHING",
            64.99: "DO NOTHING",
            65: "SELL",
            84.99: "SELL",
            85: "STRONG SELL",
            100: "STRONG SELL",
        }
        for percentile, signal in expected.items():
            self.assertEqual(signal_from_percentile(percentile), signal)

    def test_all_requested_timeframes_are_present(self):
        readings, _ = compute_timeframe_readings(
            _history(),
            now=datetime(2030, 1, 1, tzinfo=ZoneInfo("America/New_York")),
        )
        self.assertEqual(readings["Timeframe"].tolist(), list(TIMEFRAMES))

    def test_long_timeframes_have_twice_one_week_weight(self):
        self.assertEqual(
            TIMEFRAME_WEIGHTS["10 Years"],
            2 * TIMEFRAME_WEIGHTS["1 Week"],
        )
        self.assertEqual(
            TIMEFRAME_WEIGHTS["All Time"],
            2 * TIMEFRAME_WEIGHTS["1 Week"],
        )

    def test_composite_is_weighted_percentile(self):
        rows = pd.DataFrame([
            {"Timeframe": "1 Week", "Percentile": 0.0},
            {"Timeframe": "10 Years", "Percentile": 100.0},
        ])
        result = composite_signal(rows)
        self.assertAlmostEqual(result["percentile"], 200 / 3)
        self.assertEqual(result["signal"], "SELL")

    def test_incomplete_current_session_is_excluded(self):
        today = pd.Timestamp("2026-09-02")
        data = pd.DataFrame(
            {"Close": [10.0, 20.0]},
            index=[today - pd.Timedelta(days=1), today],
        )
        morning = datetime(
            2026, 9, 2, 12, 0, tzinfo=ZoneInfo("America/New_York")
        )
        at_close = datetime(
            2026, 9, 2, 16, 0, tzinfo=ZoneInfo("America/New_York")
        )
        self.assertEqual(completed_close_history(data, morning).iloc[-1], 10.0)
        self.assertEqual(completed_close_history(data, at_close).iloc[-1], 20.0)

    def test_missing_long_history_is_explicit(self):
        readings, _ = compute_timeframe_readings(
            _history(100),
            now=datetime(2030, 1, 1, tzinfo=ZoneInfo("America/New_York")),
        )
        ten_year = readings.set_index("Timeframe").loc["10 Years"]
        self.assertTrue(np.isnan(ten_year["Percentile"]))
        self.assertEqual(ten_year["Condition"], "Insufficient history")

    def test_one_close_cannot_create_a_composite_signal(self):
        data = pd.DataFrame(
            {"Close": [10.0]}, index=[pd.Timestamp("2020-01-02")]
        )
        readings, _ = compute_timeframe_readings(
            data,
            now=datetime(2030, 1, 1, tzinfo=ZoneInfo("America/New_York")),
        )
        result = composite_signal(readings)
        self.assertTrue(np.isnan(result["percentile"]))
        self.assertEqual(result["signal"], "INSUFFICIENT HISTORY")

    def test_walk_forward_study_reports_models_metrics_and_calibration(self):
        index = pd.bdate_range("2010-01-04", periods=1300)
        qqq = pd.Series(np.linspace(50, 100, len(index)), index=index)
        soxl = pd.Series(
            np.linspace(20, 80, len(index)) + np.sin(np.arange(len(index)) / 12) * 8,
            index=index,
        )
        results, calibration = walk_forward_signal_backtest(
            soxl, qqq, min_training=504, recalibrate_every=126
        )
        summary = summarize_signal_backtest(results)
        self.assertFalse(results.empty)
        self.assertFalse(calibration.empty)
        self.assertEqual(
            set(summary["Model"]), {"Composite", "SOXL-only", "QQQ-relative"}
        )
        self.assertTrue({
            "Sample size", "Median return", "Average return", "Positive rate",
            "Average drawdown", "Worst drawdown", "False-signal rate",
            "Average return CI low", "Average return CI high",
            "Reliable vs zero", "Spread vs SOXL-only",
            "Spread vs QQQ-relative", "Reliable vs SOXL-only",
            "Reliable vs QQQ-relative",
        }.issubset(summary.columns))

    def test_signal_inference_uses_blocks_and_detects_clear_separation(self):
        index = pd.bdate_range("2020-01-02", periods=240)
        results = pd.DataFrame(index=index)
        pattern = np.resize(np.array(["BUY", "SELL", "DO NOTHING"]), len(index))
        results["Composite"] = pattern
        results["SOXL-only"] = np.resize(
            np.array(["SELL", "BUY", "DO NOTHING"]), len(index)
        )
        results["QQQ-relative"] = results["SOXL-only"]
        for days in (1, 5):
            results[f"{days}d return"] = np.where(pattern == "BUY", 0.08, -0.04)
            results[f"{days}d drawdown"] = np.where(pattern == "BUY", -0.01, -0.08)

        summary = summarize_signal_backtest(
            results, holding_periods=(1, 5), n_bootstrap=200
        )
        buy_5d = summary[
            (summary["Model"] == "Composite")
            & (summary["Signal"] == "BUY")
            & (summary["Holding period"] == "5d")
        ].iloc[0]
        self.assertGreaterEqual(buy_5d["Bootstrap block"], 5)
        self.assertEqual(buy_5d["Reliable vs zero"], "Reliable positive")
        self.assertEqual(
            buy_5d["Reliable vs SOXL-only"], "Reliable positive"
        )

        report_rows = build_signal_reliability_report_rows(
            summary[summary["Holding period"] == "5d"]
        )
        average_return = next(
            row for row in report_rows
            if row["Series"] == "Composite — BUY"
            and row["Evidence"] == "Average return"
        )
        spread = next(
            row for row in report_rows
            if row["Series"] == "Composite — BUY"
            and row["Evidence"] == "Average return spread vs SOXL-only"
        )
        self.assertEqual(average_return["Reliability"], "Reliable positive")
        self.assertIn("95% CI low", average_return)
        self.assertEqual(spread["Reliability"], "Reliable positive")

    def test_market_regimes_use_trailing_data_only(self):
        index = pd.bdate_range("2018-01-02", periods=700)
        qqq = pd.Series(
            100 * np.exp(np.cumsum(0.0004 + 0.01 * np.sin(np.arange(700) / 15))),
            index=index,
        )
        first = classify_market_regimes(qqq)
        changed = qqq.copy()
        changed.iloc[600:] *= np.linspace(1, 4, 100)
        second = classify_market_regimes(changed)
        pd.testing.assert_series_equal(first.iloc[:600], second.iloc[:600])
        self.assertTrue(first.dropna().isin(["Bull", "Bear", "High volatility"]).all())

    def test_regime_summary_preserves_default_and_flags_small_samples(self):
        index = pd.bdate_range("2020-01-02", periods=120)
        results = pd.DataFrame(index=index)
        pattern = np.resize(np.array(["BUY", "SELL", "DO NOTHING"]), len(index))
        for model in ("Composite", "SOXL-only", "QQQ-relative"):
            results[model] = pattern
        results["Market regime"] = np.where(np.arange(len(index)) < 10, "Bear", "Bull")
        results["1d return"] = np.where(pattern == "BUY", 0.03, -0.01)
        results["1d drawdown"] = -0.02

        default = summarize_signal_backtest(
            results, holding_periods=(1,), n_bootstrap=100
        )
        self.assertEqual(set(default["Regime"]), {"All regimes"})

        summary = summarize_signal_backtest(
            results, holding_periods=(1,), n_bootstrap=100, include_regimes=True
        )
        self.assertEqual(
            set(summary["Regime"]),
            {"All regimes", "Bull", "Bear", "High volatility"},
        )
        bear_buy = summary[
            (summary["Regime"] == "Bear")
            & (summary["Model"] == "Composite")
            & (summary["Signal"] == "BUY")
        ].iloc[0]
        self.assertEqual(bear_buy["Evidence"], "Insufficient (<30)")
        self.assertEqual(bear_buy["Reliable vs zero"], "Insufficient data")

    def test_walk_forward_past_signals_do_not_change_when_future_changes(self):
        index = pd.bdate_range("2010-01-04", periods=1100)
        qqq = pd.Series(np.linspace(50, 100, len(index)), index=index)
        soxl = pd.Series(40 + np.sin(np.arange(len(index)) / 15) * 10, index=index)
        first, _ = walk_forward_signal_backtest(
            soxl, qqq, min_training=504, recalibrate_every=126
        )
        changed = soxl.copy()
        changed.iloc[950:] *= 4
        second, _ = walk_forward_signal_backtest(
            changed, qqq, min_training=504, recalibrate_every=126
        )
        cutoff = index[928]
        pd.testing.assert_series_equal(
            first.loc[:cutoff, "Composite"], second.loc[:cutoff, "Composite"]
        )


if __name__ == "__main__":
    unittest.main()