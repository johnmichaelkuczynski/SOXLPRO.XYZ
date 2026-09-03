import unittest

import numpy as np
import pandas as pd

from chart_payload import clean_chart_points, normalize_overlay


class ChartPayloadTests(unittest.TestCase):
    def test_clean_chart_points_drops_non_finite_and_non_positive_values(self):
        index = pd.to_datetime(
            ["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03"]
        )
        dates, prices = clean_chart_points(index, [100.0, np.nan, np.inf, 106.35])

        self.assertEqual(dates, ["2026-08-31", "2026-09-03"])
        self.assertEqual(prices, [100.0, 106.35])

    def test_normalize_overlay_keeps_all_returned_lists_aligned(self):
        index = pd.to_datetime(["2026-08-31", "2026-09-01", "2026-09-02"])
        soxl = pd.DataFrame({"Close": [100.0, 102.0, 104.0]}, index=index)
        overlay = pd.DataFrame({"Close": [50.0, np.nan, 55.0]}, index=index)

        dates, scaled, actual = normalize_overlay(soxl, overlay)

        self.assertEqual(dates, ["2026-08-31", "2026-09-02"])
        self.assertEqual(actual, [50.0, 55.0])
        self.assertEqual(scaled, [100.0, 110.0])


if __name__ == "__main__":
    unittest.main()