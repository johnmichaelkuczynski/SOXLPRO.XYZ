import unittest

import numpy as np
import pandas as pd

from ask_soxl_pro import build_ask_evidence, _fallback_answer


class AskSoxlEvidenceTests(unittest.TestCase):
    def setUp(self):
        index = pd.date_range("2020-01-01", periods=400, freq="B")
        wave = np.sin(np.arange(400) / 13.0) * 8
        self.soxl = pd.DataFrame({"Close": np.linspace(20, 100, 400) + wave}, index=index)
        self.qqq = pd.DataFrame({"Close": np.linspace(100, 200, 400)}, index=index)

    def test_probability_rows_have_explicit_samples(self):
        evidence = build_ask_evidence(self.soxl, self.qqq)
        self.assertEqual([row["horizon_trading_days"] for row in evidence.probability_rows], [21, 63, 126])
        self.assertTrue(all(row["sample_size"] > 0 for row in evidence.probability_rows))
        self.assertTrue(
            all(0 <= row["prob_additional_loss_20pct"] <= 100 for row in evidence.probability_rows)
        )

    def test_downside_zone_is_ordered_and_below_spot(self):
        evidence = build_ask_evidence(self.soxl)
        metrics = evidence.metrics
        self.assertLessEqual(
            metrics["historical_63d_stress_price_p10"],
            metrics["historical_63d_downside_price_p25"],
        )
        self.assertLessEqual(metrics["historical_63d_downside_price_p25"], metrics["current_price"])

    def test_qqq_regime_is_included_when_available(self):
        evidence = build_ask_evidence(self.soxl, self.qqq)
        self.assertIn("qqq_below_sma_200", evidence.metrics)
        self.assertFalse(evidence.metrics["qqq_below_sma_200"])

    def test_short_history_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError, "At least 30"):
            build_ask_evidence(self.soxl.head(10))

    def test_small_dataset_suppresses_unreliable_probabilities(self):
        evidence = build_ask_evidence(self.soxl.head(80))
        self.assertEqual(evidence.probability_rows, [])
        self.assertNotIn("historical_63d_stress_price_p10", evidence.metrics)

    def test_bearish_signal_denominator_counts_only_available_inputs(self):
        evidence = build_ask_evidence(self.soxl.head(80))
        self.assertEqual(evidence.metrics["bearish_signals_available"], 3)

    def test_fallback_rejects_safe_floor_claim(self):
        answer = _fallback_answer(build_ask_evidence(self.soxl, self.qqq))
        self.assertIn("No SOXL price is maximally safe", answer)
        self.assertIn("Estimated probability", answer)
        self.assertIn("Action", answer)
        self.assertIn("overlapping historical windows", answer)


if __name__ == "__main__":
    unittest.main()