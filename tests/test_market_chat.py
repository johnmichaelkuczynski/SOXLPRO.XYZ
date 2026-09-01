import unittest

import pandas as pd

from market_chat import (
    CHART_MAPPING_EXPLANATION,
    _evidence_catalog,
    _interpretation_from_evidence,
    build_market_intelligence,
)


class MarketChatGroundingTests(unittest.TestCase):
    def setUp(self):
        index = pd.bdate_range("2024-01-01", periods=320)
        self.soxl = pd.DataFrame(
            {"Close": [20 + i * 0.1 for i in range(len(index))]}, index=index
        )
        self.vix = pd.DataFrame(
            {"Close": [28 - (i % 20) * 0.5 for i in range(len(index))]}, index=index
        )

    def test_context_separates_displayed_quote_from_daily_close(self):
        context = build_market_intelligence(
            self.soxl,
            {"VIX": self.vix},
            current_soxl_price=99.0,
            quote_context={
                "state": "POST",
                "extended": True,
                "retrieved_at": "2026-09-01T17:00:00-04:00",
            },
        )
        self.assertEqual(context["soxl"]["displayed_price"], 99.0)
        self.assertNotEqual(
            context["soxl"]["displayed_price"],
            context["soxl"]["last_daily_close"],
        )
        self.assertTrue(context["soxl"]["displayed_price_is_extended_hours"])
        self.assertIn("aligned daily closes", context["analysis_basis"])

    def test_evidence_catalog_contains_only_computed_values(self):
        context = build_market_intelligence(
            self.soxl, {"VIX": self.vix}, float(self.soxl["Close"].iloc[-1])
        )
        catalog = _evidence_catalog(context)
        self.assertIn("VIX.current", catalog)
        self.assertIn("VIX.similar_move.forward_21d", catalog)
        self.assertIn("n=", catalog["VIX.similar_move.forward_21d"])

    def test_zero_event_signal_is_explicitly_unavailable(self):
        index = pd.bdate_range("2024-01-01", periods=320)
        calm_vix = pd.DataFrame({"Close": [12.0] * len(index)}, index=index)
        context = build_market_intelligence(
            self.soxl, {"VIX": calm_vix}, float(self.soxl["Close"].iloc[-1])
        )
        catalog = _evidence_catalog(context)
        statement = catalog["VIX.after_5d_spike_of_20pct_or_more.forward_21d"]
        self.assertIn("not available", statement)
        self.assertIn("n=0", statement)

    def test_interpretation_is_allowlisted_and_non_prescriptive(self):
        cases = [
            _interpretation_from_evidence("mapping", []),
            _interpretation_from_evidence("correlation", []),
            _interpretation_from_evidence(
                "signal",
                ["SOXL was higher 61.00% of the time after 21 trading days."],
            ),
            _interpretation_from_evidence(
                "signal",
                ["SOXL was higher 39.00% of the time after 21 trading days."],
            ),
            _interpretation_from_evidence(
                "signal",
                ["SOXL was higher 50.00% of the time after 21 trading days."],
            ),
            _interpretation_from_evidence("general", []),
        ]
        prohibited = [
            "buy soxl",
            "sell soxl",
            "purchase soxl",
            "accumulate soxl",
            "go long",
            "open a long position",
            "will double",
            "almost always",
        ]
        for result in cases:
            for phrase in prohibited:
                self.assertNotIn(phrase, result.lower())

    def test_chart_mapping_explanation_is_fixed_and_always_available(self):
        self.assertIn("displayed benchmark = actual benchmark", CHART_MAPPING_EXPLANATION)
        self.assertIn("visual only", CHART_MAPPING_EXPLANATION)


if __name__ == "__main__":
    unittest.main()