import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from daily_signal_scorecard import build_rating_history
from short_term_signal import (
    CANDIDATES, features, freeze_training, period_history, rule_mask,
    short_term_ratings,
)


class ShortTermSignalTests(unittest.TestCase):
    def setUp(self):
        self.closes = pd.Series(
            30 * np.exp(np.cumsum(np.sin(np.arange(600) / 7) * .025 + .001)),
            index=pd.bdate_range("2017-01-02", periods=600))

    def test_features_and_rule_matches_do_not_change_with_future_prices(self):
        before = features(self.closes.iloc[:300])
        after = features(self.closes)
        pd.testing.assert_frame_equal(before, after.iloc[:300])
        for rule in CANDIDATES:
            self.assertLessEqual(len(rule["conditions"]), 3)
            pd.testing.assert_series_equal(rule_mask(before, rule), rule_mask(after, rule).iloc[:300])

    def test_composite_feature_matches_existing_reconstruction(self):
        history = build_rating_history(self.closes)
        np.testing.assert_allclose(features(self.closes)["percentile"],
                                   history["Percentile"], equal_nan=True, atol=1e-10)

    def test_freezing_passes_only_training_data_to_candidate_evaluation(self):
        with patch("short_term_signal.candidate_history") as history, patch(
                "short_term_signal.metrics", return_value={
                    "observations": 21, "difference_pp": 5., "median_return_pct": 3.}):
            frozen = freeze_training(self.closes)
        self.assertFalse(frozen["evaluated"])
        for call in history.call_args_list:
            self.assertLessEqual(call.args[0].index.max(), pd.Timestamp("2018-12-31"))

    def test_training_outcomes_crossing_cutoff_are_not_scored(self):
        history = build_rating_history(self.closes, 21)
        training = period_history(history, "2017-01-01", "2018-12-31")
        crossing = training["Exit date"] > pd.Timestamp("2018-12-31")
        self.assertTrue(crossing.any())
        self.assertTrue(training.loc[crossing, "Return"].isna().all())
        self.assertTrue(training.loc[crossing, "Status"].eq("Awaiting outcome").all())

    def test_failed_or_insufficient_gate_is_no_edge_every_day(self):
        for n, lift, passed in [(4, 20, True), (30, 9.9, True), (50, 12, False)]:
            manifest = dict(rule=CANDIDATES[0], evaluated=True, passed=passed,
                            test_metrics=dict(observations=n, difference_pp=lift))
            self.assertTrue(short_term_ratings(self.closes, manifest).eq("NO EDGE").all())

    def test_passing_gate_fires_only_on_matching_dates(self):
        rule = dict(id="test", conditions=[["return5", "<=", 0]])
        manifest = dict(rule=rule, evaluated=True, passed=True,
                        test_metrics=dict(observations=30, difference_pp=10))
        actual = short_term_ratings(self.closes, manifest)
        self.assertTrue(actual.eq("BUY").equals(rule_mask(features(self.closes), rule)))


if __name__ == "__main__":
    unittest.main()
