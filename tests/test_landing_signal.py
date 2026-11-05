import unittest
from contextlib import nullcontext
from datetime import datetime
from types import ModuleType
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from landing_signal import (
    DEFAULT_THRESHOLDS,
    TIMEFRAMES,
    TIMEFRAME_WEIGHTS,
    _signal_card,
    completed_close_history,
    composite_signal,
    compute_timeframe_readings,
    condition_from_percentile,
    display_signal_label,
    price_range_percentile,
    render_landing_signal,
    signal_from_percentile,
)
from signal_config import (
    OLD_THRESHOLDS,
    RATING_THRESHOLDS,
    rating_bands,
    rating_threshold_description,
)
from backtest_engine import (
    build_regime_consistency_summary,
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
    def test_user_facing_signal_labels_preserve_threshold_meanings(self):
        expected = {
            "STRONG BUY": "BUY",
            "BUY": "POSSIBLE BUY",
            "DO NOTHING": "DO NOTHING",
            "SELL": "POSSIBLE SELL",
            "STRONG SELL": "SELL",
        }
        for internal, displayed in expected.items():
            self.assertEqual(display_signal_label(internal), displayed)

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

    def test_signal_boundaries_match_configured_ranges(self):
        expected = {
            0: "STRONG BUY",
            14.99: "STRONG BUY",
            15: "STRONG BUY",
            15.01: "BUY",
            54.99: "BUY",
            55: "BUY",
            55.01: "DO NOTHING",
            60: "DO NOTHING",
            64.99: "DO NOTHING",
            65: "SELL",
            84.99: "SELL",
            85: "STRONG SELL",
            100: "STRONG SELL",
        }
        for percentile, signal in expected.items():
            with self.subTest(percentile=percentile):
                self.assertEqual(signal_from_percentile(percentile), signal)

    def test_config_exports_new_and_old_thresholds(self):
        self.assertEqual(DEFAULT_THRESHOLDS, (15.0, 55.0, 65.0, 85.0))
        self.assertEqual(DEFAULT_THRESHOLDS, tuple(RATING_THRESHOLDS.values()))
        self.assertEqual(OLD_THRESHOLDS, (15.0, 35.0, 65.0, 85.0))

    def test_buy_bands_are_scaled_as_requested(self):
        bands = rating_bands()
        buy = next(band for band in bands if band["label"] == "BUY")
        possible_buy = next(band for band in bands if band["label"] == "POSSIBLE BUY")
        self.assertEqual(buy["width"], 15.0)
        self.assertEqual(possible_buy["width"], 40.0)
        self.assertEqual(signal_from_percentile(15), "STRONG BUY")
        self.assertEqual(signal_from_percentile(15.01), "BUY")
        self.assertEqual(signal_from_percentile(55), "BUY")
        self.assertEqual(signal_from_percentile(55.01), "DO NOTHING")

    def test_custom_thresholds_keep_buy_upper_bounds_inclusive(self):
        thresholds = (3.0, 12.0, 70.0, 90.0)
        expected = {
            3: "STRONG BUY",
            3.01: "BUY",
            12: "BUY",
            12.01: "DO NOTHING",
            70: "SELL",
            90: "STRONG SELL",
        }
        for percentile, signal in expected.items():
            self.assertEqual(
                signal_from_percentile(percentile, thresholds=thresholds), signal
            )

    def test_nonfinite_percentiles_are_unavailable(self):
        for percentile in (np.nan, np.inf, -np.inf):
            self.assertEqual(
                signal_from_percentile(percentile), "INSUFFICIENT HISTORY"
            )

    def test_bar_and_prose_are_generated_from_config(self):
        bands = rating_bands()
        self.assertEqual([band["width"] for band in bands], [15, 40, 10, 20, 15])
        self.assertEqual(sum(band["width"] for band in bands), 100)
        card = _signal_card(5, "STRONG BUY", "2026-10-20")
        self.assertIn("Long-term signal (6–12 months)", card)
        self.assertIn("grid-template-columns:15% 40% 10% 20% 15%", card)
        for band in bands:
            self.assertIn(f'<span>{band["label"]}</span>', card)
        prose = rating_threshold_description()
        self.assertIn("BUY: 0% through 15% (inclusive)", prose)
        self.assertIn("POSSIBLE BUY: above 15% through 55% (inclusive)", prose)
        self.assertIn("DO NOTHING: above 55% to below 65%", prose)
        self.assertIn("POSSIBLE SELL: 65% to below 85%", prose)
        self.assertIn("SELL: 85% through 100% (inclusive)", prose)

        with patch.dict(RATING_THRESHOLDS, buy_max=4, possible_buy_max=14):
            changed_card = _signal_card(5, "BUY", "2026-10-20")
            self.assertIn(
                "grid-template-columns:4% 10% 51% 20% 15%", changed_card
            )
            self.assertIn(
                "POSSIBLE BUY: above 4% through 14% (inclusive)",
                rating_threshold_description(),
            )

    def test_landing_renders_both_signals_and_preserves_scorecard_call(self):
        short_ui = ModuleType("short_term_signal_ui")
        short_ui.render_short_term_signal = Mock()
        short_ui.render_full_signal_report = Mock()
        scorecard_ui = ModuleType("signal_scorecard_ui")
        scorecard_ui.render_rating_scorecard = Mock()
        readings = pd.DataFrame([
            {"Timeframe": "1 Week", "Percentile": 5, "Condition": "Oversold"},
        ])
        closes = pd.Series([10.0, 11.0], index=pd.bdate_range("2020-01-01", periods=2))
        with (
            patch.dict("sys.modules", {
                "short_term_signal_ui": short_ui,
                "signal_scorecard_ui": scorecard_ui,
            }),
            patch("landing_signal.compute_timeframe_readings", return_value=(readings, closes)),
            patch("landing_signal.st") as streamlit,
        ):
            streamlit.columns.return_value = (nullcontext(), nullcontext())
            render_landing_signal(None)
            streamlit.columns.assert_called_once_with(2)
            short_ui.render_short_term_signal.assert_called_once_with(closes)
            short_ui.render_full_signal_report.assert_called_once_with()
            scorecard_ui.render_rating_scorecard.assert_called_once_with(closes, "BUY")

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

    def test_widening_thresholds_does_not_change_composite_percentile(self):
        rows = pd.DataFrame([
            {"Timeframe": "1 Week", "Percentile": 5.0},
            {"Timeframe": "10 Years", "Percentile": 20.0},
            {"Timeframe": "All Time", "Percentile": np.nan},
        ])
        new = composite_signal(rows)
        old_bounds = composite_signal(rows, thresholds=OLD_THRESHOLDS)
        self.assertEqual(new["percentile"], old_bounds["percentile"])
        self.assertEqual(new["percentile"], 15.0)
        self.assertEqual(new["signal"], "STRONG BUY")

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

    def test_regime_consistency_summary_is_scoped_and_text_labeled(self):
        rows = []
        states = {
            "Bull": "Reliable positive",
            "Bear": "Reliable negative",
            "High volatility": "Not reliable",
        }
        for horizon in ("5d", "21d"):
            for regime, state in states.items():
                rows.append({
                    "Holding period": horizon,
                    "Regime": regime,
                    "Model": "Composite",
                    "Signal": "BUY",
                    "Reliable vs zero": (
                        "Insufficient data"
                        if horizon == "5d" and regime == "Bear"
                        else state
                    ),
                })
        matrix = build_regime_consistency_summary(pd.DataFrame(rows), "5d")

        self.assertEqual(
            matrix.columns.tolist(),
            ["Model", "Signal", "Bull", "Bear", "High volatility"],
        )
        self.assertEqual(len(matrix), 1)
        self.assertEqual(matrix.iloc[0]["Bull"], "↑ Reliable positive")
        self.assertEqual(matrix.iloc[0]["Bear"], "? Insufficient evidence")
        self.assertEqual(matrix.iloc[0]["High volatility"], "○ Not reliable")

    def test_regime_consistency_summary_fills_missing_regimes(self):
        summary = pd.DataFrame([{
            "Holding period": "21d",
            "Regime": "Bull",
            "Model": "Composite",
            "Signal": "SELL",
            "Reliable vs zero": "Reliable negative",
        }])
        matrix = build_regime_consistency_summary(summary, "21d")

        self.assertEqual(matrix.iloc[0]["Bull"], "↓ Reliable negative")
        self.assertEqual(matrix.iloc[0]["Bear"], "? Insufficient evidence")
        self.assertEqual(
            matrix.iloc[0]["High volatility"], "? Insufficient evidence"
        )

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
