"""Unit tests for causal time--price area feature construction."""

import unittest

import numpy as np
import pandas as pd

from area_lab.features import FEATURE_COLUMNS, add_targets, build_features


def _bars(values, lows=None, highs=None):
    index = pd.date_range("2024-01-01", periods=len(values), freq="D")
    close = np.asarray(values, dtype=float)
    if lows is None:
        lows = close - 0.5
    if highs is None:
        highs = close + 0.5
    return pd.DataFrame(
        {
            "Open": close,
            "High": np.asarray(highs, dtype=float),
            "Low": np.asarray(lows, dtype=float),
            "Close": close,
        },
        index=index,
    )


class AreaLabFeaturesTests(unittest.TestCase):
    def test_public_schema_and_fixed_numeric_formulas(self):
        bars = _bars([10, 11, 12, 13, 14, 15])
        features = build_features(
            bars,
            {
                "anchor_mode": "fixed",
                "fixed_anchor": "2024-01-02",
                "normalization": "none",
                "lookback": 5,
            },
        )
        self.assertEqual(list(features.columns), FEATURE_COLUMNS)
        self.assertTrue(pd.isna(features.iloc[0]["anchor_price"]))
        # The fixed anchor is the first trading date on/after 2024-01-02.
        self.assertEqual(features.iloc[1]["anchor_price"], 11.0)
        self.assertEqual(features.iloc[3]["elapsed_sessions"], 2.0)
        self.assertAlmostEqual(features.iloc[3]["area_log"], 2 * np.log(13 / 11))
        self.assertAlmostEqual(features.iloc[3]["area_signed"], 2 * np.log(13 / 11))
        self.assertAlmostEqual(features.iloc[3]["area_norm"], features.iloc[3]["area_log"])

    def test_all_anchor_modes_are_supported(self):
        bars = _bars([10, 9, 8, 9, 10, 11, 10, 9, 8, 9, 10])
        configs = [
            {"anchor_mode": "low20", "lookback": 5},
            {"anchor_mode": "high20", "lookback": 5},
            {"anchor_mode": "rolling", "lookback": 5},
            {"anchor_mode": "swing_low", "pivot_bars": 1},
            {"anchor_mode": "swing_high", "pivot_bars": 1},
            {
                "anchor_mode": "fixed",
                "fixed_anchor": "2024-01-03",
            },
        ]
        for config in configs:
            with self.subTest(mode=config["anchor_mode"]):
                result = build_features(bars, config)
                self.assertEqual(result.shape[1], len(FEATURE_COLUMNS))
                self.assertEqual(len(result), len(bars))

    def test_named_twenty_day_extremes_ignore_rolling_lookback_control(self):
        values = 100 + np.sin(np.arange(70) / 3.0) * 8 + np.arange(70) / 10
        bars = _bars(values)
        for mode in ("low20", "high20"):
            with self.subTest(mode=mode):
                short = build_features(
                    bars,
                    {
                        "anchor_mode": mode,
                        "lookback": 5,
                        "normalization": "none",
                    },
                )
                long = build_features(
                    bars,
                    {
                        "anchor_mode": mode,
                        "lookback": 60,
                        "normalization": "none",
                    },
                )
                for column in (
                    "anchor_date",
                    "anchor_price",
                    "anchor_type",
                    "anchor_confirmation_date",
                    "elapsed_sessions",
                    "area_raw",
                    "area_log",
                    "area_signed",
                    "area_norm",
                ):
                    pd.testing.assert_series_equal(
                        short[column], long[column], check_names=False
                    )

    def test_rolling_anchor_is_start_of_current_window(self):
        bars = _bars([10, 11, 12, 13, 14, 15, 16])
        result = build_features(
            bars,
            {
                "anchor_mode": "rolling",
                "lookback": 5,
                "normalization": "none",
            },
        )
        self.assertTrue(pd.isna(result.iloc[3]["anchor_date"]))
        self.assertEqual(result.iloc[4]["anchor_date"], bars.index[0])
        self.assertEqual(result.iloc[4]["anchor_price"], 10.0)
        self.assertEqual(result.iloc[4]["elapsed_sessions"], 4.0)
        self.assertEqual(result.iloc[6]["anchor_date"], bars.index[2])

    def test_swing_pivot_is_unavailable_until_confirmation(self):
        values = [10, 8, 10, 11, 12, 11, 10]
        bars = _bars(values, lows=np.asarray(values) - 0.1)
        result = build_features(
            bars,
            {
                "anchor_mode": "swing_low",
                "pivot_bars": 1,
                "normalization": "none",
            },
        )
        self.assertTrue(pd.isna(result.iloc[1]["anchor_date"]))
        self.assertEqual(result.iloc[2]["anchor_date"], bars.index[1])
        self.assertEqual(result.iloc[2]["anchor_price"], bars.iloc[1]["Low"])
        self.assertEqual(
            result.iloc[2]["anchor_confirmation_date"], bars.index[2]
        )

    def test_future_perturbation_does_not_change_past_features(self):
        bars = _bars([10, 9, 11, 10, 12, 11, 13, 12])
        first = build_features(
            bars,
            {
                "anchor_mode": "rolling",
                "lookback": 5,
                "normalization": "none",
            },
        )
        changed = bars.copy()
        changed.iloc[-1, changed.columns.get_loc("Close")] = 100
        changed.iloc[-1, changed.columns.get_loc("Open")] = 100
        changed.iloc[-1, changed.columns.get_loc("High")] = 101
        changed.iloc[-1, changed.columns.get_loc("Low")] = 99
        second = build_features(
            changed,
            {
                "anchor_mode": "rolling",
                "lookback": 5,
                "normalization": "none",
            },
        )
        pd.testing.assert_frame_equal(
            first.iloc[:-1].reset_index(drop=True),
            second.iloc[:-1].reset_index(drop=True),
        )

    def test_targets_use_the_later_row_anchor(self):
        bars = _bars([10, 11, 9, 10, 12, 11, 13])
        features = build_features(
            bars,
            {
                "anchor_mode": "rolling",
                "lookback": 5,
                "normalization": "none",
            },
        )
        # Use an explicit synthetic feature frame to isolate the target shift.
        features.loc[:, "area_log"] = np.arange(len(features), dtype=float)
        features.loc[:, "area_norm"] = 10 + np.arange(len(features), dtype=float)
        result = add_targets(features, [2])
        self.assertEqual(result.iloc[0]["future_area_log_2"], 2.0)
        self.assertEqual(result.iloc[0]["future_area_norm_2"], 12.0)
        self.assertEqual(result.iloc[0]["future_area_change_2"], 2.0)
        self.assertEqual(result.iloc[0]["future_norm_area_change_2"], 2.0)
        self.assertTrue(pd.isna(result.iloc[-1]["target_date_2"]))

    def test_bad_ohlc_fails_explicitly(self):
        bars = _bars([10, 11, 12])
        bars.iloc[1, bars.columns.get_loc("High")] = 5
        with self.assertRaisesRegex(ValueError, "Invalid OHLC"):
            build_features(bars)


if __name__ == "__main__":
    unittest.main()