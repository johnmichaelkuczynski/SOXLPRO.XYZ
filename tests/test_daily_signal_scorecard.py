import unittest

import numpy as np
import pandas as pd

from daily_signal_scorecard import (
    HISTORY_COLUMNS,
    build_rating_history,
    summarize_ratings,
)
from landing_signal import (
    TIMEFRAMES,
    TIMEFRAME_WEIGHTS,
    composite_signal,
    compute_timeframe_readings,
    display_signal_label,
)


def _closes(values, start="2020-01-02"):
    return pd.Series(
        values,
        index=pd.bdate_range(start, periods=len(values)),
        dtype=float,
        name="Close",
    )


def _manual_history(ratings, returns, horizon=5):
    index = pd.bdate_range("2020-01-02", periods=len(ratings))
    completed = [value is not None for value in returns]
    result = pd.DataFrame(
        {
            "Rating": ratings,
            "Percentile": 50.0,
            "Rating close": 100.0,
            "Entry date": index,
            "Entry close": 100.0,
            "Exit date": index,
            "Exit close": 100.0,
            "Return": [value if value is not None else np.nan for value in returns],
            "Worst drawdown": [
                -(abs(value) / 2) if value is not None else np.nan
                for value in returns
            ],
            "Status": [
                "Completed" if is_complete else "Awaiting outcome"
                for is_complete in completed
            ],
        },
        index=pd.Index(index, name="Rating date"),
    )
    result.attrs["horizon"] = horizon
    return result


class DailySignalScorecardTests(unittest.TestCase):
    def test_output_interface_and_empty_bad_data(self):
        empty = build_rating_history(pd.Series(dtype=float), horizon=5)
        self.assertEqual(empty.columns.tolist(), list(HISTORY_COLUMNS))
        self.assertEqual(empty.index.name, "Rating date")
        self.assertEqual(empty.attrs["horizon"], 5)
        self.assertTrue(
            build_rating_history(
                pd.Series(
                    ["bad", 0, -2, np.inf, np.nan],
                    index=["bad date", "2020-01-02", "2020-01-03",
                           "2020-01-04", "2020-01-05"],
                ),
                horizon=5,
            ).empty
        )
        with self.assertRaises(ValueError):
            build_rating_history(_closes([1, 2]), horizon=7)

    def test_cleaning_is_positive_finite_sorted_and_deduplicated(self):
        dates = pd.to_datetime(
            ["2020-01-03", "2020-01-02", "2020-01-02", "2020-01-06"]
        )
        closes = pd.Series([3.0, 1.0, 2.0, 4.0], index=dates)
        history = build_rating_history(closes, horizon=5)
        self.assertEqual(
            history.index.tolist(),
            list(pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])),
        )
        self.assertEqual(history.loc["2020-01-02", "Rating close"], 2.0)

    def test_prefix_ratings_match_landing_formula_for_early_and_full_windows(self):
        closes = _closes(
            [10, 13, 11, 17, 14, 22, 9, 18, 24, 20, 29, 16, 31, 12, 34]
        )
        history = build_rating_history(closes, horizon=5)
        for position, date in enumerate(closes.index):
            prefix = closes.iloc[: position + 1]
            readings, _ = compute_timeframe_readings(
                pd.DataFrame({"Close": prefix}),
                now=pd.Timestamp("2030-01-01").to_pydatetime(),
            )
            expected = composite_signal(readings)
            actual = history.loc[date]
            if np.isnan(expected["percentile"]):
                self.assertTrue(np.isnan(actual["Percentile"]))
                self.assertEqual(actual["Rating"], "INSUFFICIENT HISTORY")
            else:
                self.assertAlmostEqual(
                    actual["Percentile"], expected["percentile"], places=12
                )
                self.assertEqual(
                    actual["Rating"], display_signal_label(expected["signal"])
                )

    def test_constant_history_is_unavailable(self):
        history = build_rating_history(_closes([10.0] * 20), horizon=5)
        self.assertTrue(history["Percentile"].isna().all())
        self.assertEqual(set(history["Rating"]), {"INSUFFICIENT HISTORY"})
        self.assertTrue((history["Status"] == "Insufficient history").all())

    def test_future_edits_do_not_change_past_ratings(self):
        closes = _closes(np.linspace(10.0, 70.0, 45))
        first = build_rating_history(closes, horizon=5)
        changed = closes.copy()
        changed.iloc[-10:] *= 8
        second = build_rating_history(changed, horizon=5)
        pd.testing.assert_frame_equal(
            first.iloc[:-10][["Rating", "Percentile"]],
            second.iloc[:-10][["Rating", "Percentile"]],
        )

    def test_entry_is_next_close_and_exit_is_horizon_sessions_after_entry(self):
        closes = _closes(np.arange(10.0, 31.0))
        history = build_rating_history(closes, horizon=5)
        row = history.iloc[1]
        self.assertEqual(row["Entry date"], closes.index[2])
        self.assertEqual(row["Entry close"], closes.iloc[2])
        self.assertEqual(row["Exit date"], closes.index[7])
        self.assertEqual(row["Exit close"], closes.iloc[7])
        self.assertAlmostEqual(row["Return"], closes.iloc[7] / closes.iloc[2] - 1)
        self.assertAlmostEqual(row["Worst drawdown"], 0.0)

    def test_pending_outcomes_have_no_return_or_drawdown_leakage(self):
        closes = _closes(np.arange(10.0, 24.0))
        history = build_rating_history(closes, horizon=5)
        pending = history[history["Status"] == "Awaiting outcome"]
        self.assertFalse(pending.empty)
        self.assertTrue(pending["Return"].isna().all())
        self.assertTrue(pending["Worst drawdown"].isna().all())
        summary = summarize_ratings(history)
        self.assertEqual(
            summary.loc[summary["Rating"] == "All rated days", "Completed"].iloc[0],
            int((history["Status"] == "Completed").sum()),
        )
        self.assertEqual(
            summary.loc[summary["Rating"] == "All rated days", "Pending"].iloc[0],
            len(pending),
        )
        self.assertEqual(
            summary.loc[summary["Rating"] != "All rated days", "Completed"].sum(),
            int((history["Status"] == "Completed").sum()),
        )

    def test_drawdown_uses_entry_through_exit_path(self):
        closes = _closes([10, 20, 30, 20, 50, 60, 25, 70, 80])
        history = build_rating_history(closes, horizon=5)
        row = history.iloc[1]
        self.assertAlmostEqual(row["Worst drawdown"], 20 / 30 - 1)

    def test_summary_uses_same_baseline_denominator_and_lifts(self):
        ratings = ["BUY", "SELL", "BUY", "SELL", "BUY", "SELL", "BUY"]
        history = _manual_history(
            ratings, [0.10, -0.10, 0.20, -0.20, None, None, None]
        )
        summary = summarize_ratings(history)
        all_days = summary.iloc[0]
        buy = summary[summary["Rating"] == "BUY"].iloc[0]
        sell = summary[summary["Rating"] == "SELL"].iloc[0]
        self.assertEqual(all_days["Rated days"], 7)
        self.assertEqual(all_days["Completed"], 4)
        self.assertEqual(all_days["Pending"], 3)
        self.assertEqual(all_days["Win rate"], 0.5)
        self.assertEqual(buy["Completed"], 2)
        self.assertEqual(buy["Win rate"], 1.0)
        self.assertAlmostEqual(buy["Win-rate lift"], 0.5)
        self.assertEqual(sell["Win rate"], 0.0)
        self.assertAlmostEqual(sell["Average-return lift"], -0.15)

    def test_non_overlapping_is_one_global_schedule(self):
        ratings = ["BUY"] * 18
        ratings[1] = "SELL"
        ratings[7] = "SELL"
        history = _manual_history(ratings, [0.01] * 18, horizon=5)
        summary = summarize_ratings(history, non_overlapping=True)
        all_days = summary.iloc[0]
        sell = summary[summary["Rating"] == "SELL"].iloc[0]
        self.assertEqual(all_days["Rated days"], 3)  # positions 0, 6, 12
        self.assertEqual(all_days["Completed"], 3)
        self.assertEqual(sell["Rated days"], 0)
        self.assertTrue(np.isnan(sell["Average return"]))

    def test_all_display_labels_are_exact(self):
        expected = {
            "STRONG BUY": "BUY",
            "BUY": "POSSIBLE BUY",
            "DO NOTHING": "DO NOTHING",
            "SELL": "POSSIBLE SELL",
            "STRONG SELL": "SELL",
            "INSUFFICIENT HISTORY": "INSUFFICIENT HISTORY",
        }
        observed = {
            display_signal_label(internal)
            for internal in expected
        }
        self.assertEqual(observed, set(expected.values()))
        self.assertEqual(
            list(TIMEFRAMES),
            [
                "1 Week", "1 Month", "3 Months", "6 Months", "1 Year",
                "2 Years", "3 Years", "5 Years", "10 Years", "All Time",
            ],
        )
        self.assertEqual(TIMEFRAME_WEIGHTS["All Time"], 2.0)


if __name__ == "__main__":
    unittest.main()