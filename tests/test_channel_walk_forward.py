import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from area_lab.channel_validation import (
    PROTOCOL, build_windows, first_passage, forecast_at, walk_forward,
)


def prices(count=750):
    rng = np.random.default_rng(41)
    return pd.Series(10 * np.exp(np.cumsum(rng.normal(.0005, .035, count))),
                     index=pd.bdate_range("2010-01-01", periods=count))


class ChannelWalkForwardTests(unittest.TestCase):
    def test_channel_and_area_use_only_prefix(self):
        data = prices()
        cutoff = 400
        before = forecast_at(data.iloc[:cutoff + 1], data.index[cutoff + 21])
        data.iloc[cutoff + 1:] *= 100
        after = forecast_at(data.iloc[:cutoff + 1], data.index[cutoff + 21])
        self.assertEqual(before, after)
        history = data.iloc[:cutoff + 1]
        x = (history.index - history.index[0]).days.to_numpy()
        slope = np.polyfit(x, np.log10(history), 1)[0]
        offsets = np.log10(history) - slope * x
        for row, intercept in zip(before, [offsets.min(), offsets.median(), offsets.max()]):
            target = 10 ** (intercept + slope * (row["deadline"] - history.index[0]).days)
            self.assertAlmostEqual(row["target_price"], target, places=8)
        expected_area = (history.index[-1] - history.index[-21]).days * abs(
            np.log10(history.iloc[-1] / history.iloc[-21]))
        self.assertAlmostEqual(before[0]["area"], expected_area)

    def test_downward_target_is_not_already_hit(self):
        self.assertLess(first_passage(np.log(.5), .1, .4, 1), 1)
        self.assertAlmostEqual(first_passage(.4, 0, .4, 1), .3173105079, places=8)
        self.assertAlmostEqual(first_passage(.4, 0, .4, 1), first_passage(-.4, 0, .4, 1))

    def test_outcomes_are_future_directional_closes(self):
        data = prices(400)
        windows = build_windows(data)
        for row in windows.itertuples():
            future = data.iloc[row.origin_pos + 1:row.deadline_pos + 1]
            expected = future.max() >= row.target_price if row.direction == "up" else future.min() <= row.target_price
            self.assertEqual(row.hit, expected)
            self.assertEqual(row.fit_end, row.origin)

    def test_future_mutation_cannot_change_earlier_predictions(self):
        data = prices()
        original = build_windows(data)
        # Small minimum is only for this synthetic unit test, never the report.
        with patch.dict(PROTOCOL, minimum_training_origins=5):
            predictions = walk_forward(original)
            cutoff = data.index[580]
            data.loc[data.index > cutoff] *= 20
            altered = walk_forward(build_windows(data))
        self.assertFalse(predictions.empty)
        self.assertTrue((predictions.training_last_outcome <= predictions.origin).all())
        cols = ["origin", "horizon", "line", "target_price", "raw_probability",
                "calibrated_probability", "area_probability", "training_last_outcome"]
        a = predictions.loc[predictions.origin <= cutoff, cols].reset_index(drop=True)
        b = altered.loc[altered.origin <= cutoff, cols].reset_index(drop=True)
        pd.testing.assert_frame_equal(a, b)

    def test_short_or_invalid_data_fail_explicitly(self):
        with self.assertRaises(ValueError):
            forecast_at(prices(200), pd.Timestamp("2020-01-01"))
        broken = prices()
        broken.iloc[50] = np.nan
        with self.assertRaises(ValueError):
            build_windows(broken)


if __name__ == "__main__":
    unittest.main()
