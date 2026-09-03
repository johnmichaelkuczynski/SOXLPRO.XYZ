import unittest

import numpy as np
import pandas as pd

from call_risk_reward import (
    _heatmap_contract_label,
    DEFAULT_SCENARIOS,
    _stratified_limit,
    build_return_heatmap,
    prepare_call_metrics,
)


def _sample_chain():
    return pd.DataFrame([
        {
            "kind": "c",
            "contract_symbol": "SOXL_LEAP_ITM",
            "strike": 30.0,
            "dte": 600,
            "exp_date": "2028-04-18",
            "yf_iv": 0.75,
            "bid": 39.50,
            "ask": 40.00,
            "volume": 12,
            "open_interest": 1200,
        },
        {
            "kind": "c",
            "contract_symbol": "SOXL_ATM",
            "strike": 70.0,
            "dte": 90,
            "exp_date": "2026-11-25",
            "yf_iv": 0.90,
            "bid": 10.50,
            "ask": 11.00,
            "volume": 100,
            "open_interest": 900,
        },
        {
            "kind": "c",
            "contract_symbol": "SOXL_OTM",
            "strike": 90.0,
            "dte": 14,
            "exp_date": "2026-09-10",
            "yf_iv": 1.10,
            "bid": 0.45,
            "ask": 0.55,
            "volume": 300,
            "open_interest": 1500,
        },
        {
            "kind": "p",
            "contract_symbol": "SOXL_PUT",
            "strike": 70.0,
            "dte": 14,
            "exp_date": "2026-09-10",
            "yf_iv": 1.10,
            "bid": 3.00,
            "ask": 3.20,
            "volume": 300,
            "open_interest": 1500,
        },
    ])


class CallRiskRewardTests(unittest.TestCase):
    def test_non_finite_spot_returns_no_metrics(self):
        raw = _sample_chain()
        self.assertTrue(prepare_call_metrics(raw, np.nan).empty)

    def test_heatmap_row_puts_strike_first_and_labels_it(self):
        row = pd.Series({
            "risk_score": 68.4,
            "expiration": "2028-01-21",
            "strike": 425.0,
            "money_label": "OTM",
        })
        label = _heatmap_contract_label(row)
        self.assertTrue(label.startswith("STRIKE $425"))
        self.assertIn("Jan 21, 2028", label)
        self.assertIn("Risk 68", label)

    def test_prepare_call_metrics_uses_ask_and_standard_contract(self):
        metrics = prepare_call_metrics(_sample_chain(), spot=70.0)
        otm = metrics.loc[metrics["contract_symbol"] == "SOXL_OTM"].iloc[0]

        self.assertEqual(len(metrics), 3)
        self.assertTrue(np.isclose(otm["cost_contract"], 55.0))
        self.assertTrue(np.isclose(otm["max_loss_contract"], 55.0))
        self.assertTrue(np.isclose(otm["breakeven"], 90.55))
        self.assertTrue(np.isclose(otm["roi_-30"], -100.0))

        ending_spot = 70.0 * 2.0
        expected_pnl = (ending_spot - 90.0) * 100.0 - 55.0
        self.assertTrue(np.isclose(otm["pnl_+100"], expected_pnl))
        self.assertTrue(
            np.isclose(otm["roi_+100"], expected_pnl / 55.0 * 100.0)
        )

    def test_risk_reward_order_is_intuitive_for_representative_contracts(self):
        metrics = prepare_call_metrics(_sample_chain(), spot=70.0)
        leap = metrics.loc[
            metrics["contract_symbol"] == "SOXL_LEAP_ITM"
        ].iloc[0]
        otm = metrics.loc[metrics["contract_symbol"] == "SOXL_OTM"].iloc[0]

        self.assertLess(leap["risk_score"], otm["risk_score"])
        self.assertLess(leap["prob_loss_pct"], otm["prob_loss_pct"])
        self.assertLess(leap["roi_+100"], otm["roi_+100"])

    def test_missing_iv_keeps_payoff_but_does_not_invent_probability(self):
        raw = _sample_chain().iloc[[0]].copy()
        raw["yf_iv"] = np.nan
        metrics = prepare_call_metrics(raw, spot=70.0)

        self.assertTrue(np.isnan(metrics.iloc[0]["risk_score"]))
        self.assertTrue(np.isnan(metrics.iloc[0]["prob_profit_pct"]))
        self.assertTrue(np.isfinite(metrics.iloc[0]["roi_+30"]))

    def test_heatmap_contains_every_scenario_and_visible_text(self):
        metrics = prepare_call_metrics(_sample_chain(), spot=70.0)
        figure = build_return_heatmap(metrics, spot=70.0)
        trace = figure.data[0]

        self.assertEqual(trace.z.shape, (3, len(DEFAULT_SCENARIOS)))
        self.assertEqual(trace.text.shape, trace.z.shape)
        self.assertIn("-100%", set(trace.text.flatten()))

    def test_contract_limit_preserves_each_expiration(self):
        rows = []
        for exp_number, expiration in enumerate(
            ["2026-09-18", "2026-12-18", "2027-06-18"]
        ):
            for strike in range(40, 140, 10):
                rows.append({
                    "expiration": expiration,
                    "dte": 30 + exp_number * 180,
                    "strike": float(strike),
                    "open_interest": 100,
                    "volume": 10,
                    "spread_pct": 5.0,
                })
        limited = _stratified_limit(pd.DataFrame(rows), maximum=12)

        self.assertEqual(len(limited), 12)
        self.assertEqual(
            set(limited["expiration"]),
            {"2026-09-18", "2026-12-18", "2027-06-18"},
        )


if __name__ == "__main__":
    unittest.main()