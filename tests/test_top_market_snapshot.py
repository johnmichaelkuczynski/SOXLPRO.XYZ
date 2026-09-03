import unittest

import numpy as np
import pandas as pd

from top_market_snapshot import compute_market_snapshot


class TopMarketSnapshotTests(unittest.TestCase):
    def test_calculates_requested_returns_and_52_week_range(self):
        dates = pd.bdate_range("2014-01-02", "2026-01-02")
        closes = pd.Series(np.linspace(10.0, 110.0, len(dates)), index=dates)
        data = pd.DataFrame({"Close": closes})

        result = compute_market_snapshot(
            data,
            quote={
                "price": 112.0,
                "prev_close": 110.0,
                "state": "REGULAR",
                "extended": False,
            },
        )

        self.assertAlmostEqual(result["current_price"], 112.0)
        self.assertAlmostEqual(result["returns"]["Day"], 112 / 110 * 100 - 100)
        self.assertEqual(
            list(result["returns"]),
            ["Day", "Week", "Month", "Year", "3 Years", "5 Years", "10 Years", "All Time"],
        )
        self.assertTrue(np.isfinite(result["returns"]["10 Years"]))
        self.assertAlmostEqual(result["week_52_high"], 112.0)
        self.assertLess(result["week_52_low"], result["week_52_high"])

    def test_missing_history_is_explicit_and_close_is_fallback(self):
        dates = pd.bdate_range("2025-01-02", periods=10)
        data = pd.DataFrame({"Close": np.arange(10.0, 20.0)}, index=dates)

        result = compute_market_snapshot(data)

        self.assertEqual(result["current_price"], 19.0)
        self.assertAlmostEqual(result["returns"]["Day"], 19 / 18 * 100 - 100)
        self.assertTrue(np.isnan(result["returns"]["Year"]))
        self.assertTrue(np.isnan(result["returns"]["10 Years"]))
        self.assertEqual(result["week_52_high"], 19.0)
        self.assertEqual(result["week_52_low"], 10.0)

    def test_non_finite_prices_are_ignored(self):
        data = pd.DataFrame(
            {"Close": [10.0, np.nan, np.inf, 12.0]},
            index=pd.bdate_range("2026-01-02", periods=4),
        )
        result = compute_market_snapshot(data)
        self.assertEqual(result["current_price"], 12.0)
        self.assertAlmostEqual(result["returns"]["Day"], 20.0)


if __name__ == "__main__":
    unittest.main()