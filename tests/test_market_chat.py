import unittest

import pandas as pd

from market_chat import (
    CHART_MAPPING_EXPLANATION,
    PRODUCT_EVIDENCE,
    _deterministic_product_evidence,
    _evidence_catalog,
    _needs_mapping,
    _safe_fallback,
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

    def test_fallback_is_allowlisted_and_non_prescriptive(self):
        cases = [
            _safe_fallback("mapping", []),
            _safe_fallback("correlation", []),
            _safe_fallback(
                "signal",
                ["SOXL was higher 61.00% of the time after 21 trading days."],
            ),
            _safe_fallback(
                "signal",
                ["SOXL was higher 39.00% of the time after 21 trading days."],
            ),
            _safe_fallback(
                "signal",
                ["SOXL was higher 50.00% of the time after 21 trading days."],
            ),
            _safe_fallback("general", []),
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
        self.assertTrue(_needs_mapping("What do these lines mean?", False))
        self.assertTrue(_needs_mapping("Explain this overlay", False))

    def test_product_knowledge_covers_non_chart_features(self):
        self.assertIn("APP.call_payoff", PRODUCT_EVIDENCE)
        self.assertIn("APP.risk_score", PRODUCT_EVIDENCE)
        self.assertIn("APP.dislocation", PRODUCT_EVIDENCE)
        self.assertIn("APP.backtest_data", PRODUCT_EVIDENCE)
        self.assertIn("APP.vol_surface", PRODUCT_EVIDENCE)
        self.assertIn("APP.diagnostic", PRODUCT_EVIDENCE)

    def test_product_evidence_uses_full_conversation_context(self):
        ids = _deterministic_product_evidence(
            "Explain the Call Risk Score. How is that different from the Vol Surface?"
        )
        self.assertIn("APP.risk_score", ids)
        self.assertIn("APP.call_payoff", ids)
        self.assertIn("APP.vol_surface", ids)

    def test_product_fallback_answers_follow_up_specifically(self):
        answer = _safe_fallback(
            "general",
            [],
            "Explain the Call Risk Score. How is that different from the Vol Surface?",
        )
        self.assertIn("Call Risk/Reward", answer)
        self.assertIn("Vol Surface", answer)
        self.assertIn("different question", answer)

    def test_all_advertised_tools_have_specific_failure_paths(self):
        cases = {
            "Explain the Probability Engine": "Probability Engine",
            "Explain the Call Risk Score": "Call Risk Score",
            "Explain the Vol Surface": "Vol Surface",
            "Explain SOXL-QQQ Dislocation": "Dislocation",
            "Explain Strategy Builder": "Strategy Builder",
            "Explain Backtest": "Backtest",
            "What does Diagnostic check?": "Diagnostic",
        }
        for question, expected in cases.items():
            evidence_ids = _deterministic_product_evidence(question)
            self.assertTrue(evidence_ids, question)
            answer = _safe_fallback("general", [], question)
            self.assertIn(expected, answer, question)

    def test_strategy_builder_backtest_comparison_uses_both_tools(self):
        question = "How is Strategy Builder different from Backtest?"
        evidence_ids = _deterministic_product_evidence(question)
        self.assertIn("APP.strategy_builder", evidence_ids)
        self.assertIn("APP.backtest_data", evidence_ids)
        answer = _safe_fallback("general", [], question)
        self.assertIn("Strategy Builder", answer)
        self.assertIn("Backtest", answer)
        self.assertIn("different roles", answer)


if __name__ == "__main__":
    unittest.main()