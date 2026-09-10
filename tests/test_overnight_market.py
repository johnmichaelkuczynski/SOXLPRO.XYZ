import unittest
from unittest.mock import patch

import pandas as pd

from overnight_market import build_overnight_rows, overnight_chart, fetch_overnight_market, ET


def prices(times, values):
    return pd.DataFrame({"Close": values}, index=pd.to_datetime(times).tz_localize(ET))


def schedule(date, close="16:00"):
    return {
        "pre_start": pd.Timestamp(date + " 04:00", tz=ET),
        "start": pd.Timestamp(date + " 09:30", tz=ET),
        "end": pd.Timestamp(date + " " + close, tz=ET),
        "post_end": pd.Timestamp(date + " 20:00", tz=ET),
    }


class OvernightMarketTests(unittest.TestCase):
    def setUp(self):
        self.daily = prices(["2026-09-04", "2026-09-08", "2026-09-09"], [100, 110, 120])
        self.periods = pd.DataFrame([schedule("2026-09-08"), schedule("2026-09-09")])

    def test_pre_market_uses_previous_close_and_evening_uses_same_day_close(self):
        bars = prices(["2026-09-08 16:00", "2026-09-09 04:00", "2026-09-09 16:00"],
                      [111, 112, 119])
        rows = build_overnight_rows(bars, self.daily, self.periods)
        self.assertEqual(list(rows.baseline), [110, 110, 120])
        self.assertEqual(list(rows.baseline_date), ["2026-09-08", "2026-09-08", "2026-09-09"])
        self.assertAlmostEqual(rows.iloc[1].change_pct, 100 * 2 / 110)
        self.assertEqual(rows.iloc[2].change, -1)

    def test_holiday_and_weekend_gap_uses_last_trading_close(self):
        rows = build_overnight_rows(prices(["2026-09-08 04:00"], [103]), self.daily, self.periods)
        self.assertEqual(rows.iloc[0].baseline_date, "2026-09-04")
        self.assertAlmostEqual(rows.iloc[0].change_pct, 3)

    def test_regular_and_uncovered_hours_are_excluded(self):
        bars = prices(["2026-09-09 03:55", "2026-09-09 09:30", "2026-09-09 15:55",
                       "2026-09-09 20:00"], [100] * 4)
        self.assertTrue(build_overnight_rows(bars, self.daily, self.periods).empty)

    def test_early_close_is_taken_from_provider_schedule(self):
        early = pd.DataFrame([schedule("2026-09-09", close="13:00")])
        rows = build_overnight_rows(prices(["2026-09-09 13:00"], [123]), self.daily, early)
        self.assertEqual(rows.iloc[0].session, "After-hours")
        self.assertEqual(rows.iloc[0].baseline, 120)

    def test_missing_same_day_close_does_not_use_older_close(self):
        rows = build_overnight_rows(prices(["2026-09-09 16:00"], [122]),
                                    self.daily.iloc[:-1], self.periods)
        self.assertTrue(rows.empty)

    def test_bad_prices_filtered_and_duplicate_bars_deduplicated(self):
        bars = prices(["2026-09-09 04:00", "2026-09-09 04:00", "2026-09-09 04:05",
                       "2026-09-09 04:10", "2026-09-09 04:15"], [111, 112, 0, float("inf"), -1])
        rows = build_overnight_rows(bars, self.daily, self.periods)
        self.assertEqual(list(rows.price), [112])

    def test_missing_schedule_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError, "schedule unavailable"):
            build_overnight_rows(prices(["2026-09-09 04:00"], [112]), self.daily, None)

    def test_timezone_conversion_across_daylight_saving(self):
        daily = prices(["2026-03-06"], [50])
        bars = pd.DataFrame({"Close": [52]}, index=pd.to_datetime(["2026-03-09T08:00:00Z"]))
        rows = build_overnight_rows(bars, daily, pd.DataFrame([schedule("2026-03-09")]))
        self.assertEqual(rows.iloc[0].time.hour, 4)
        self.assertAlmostEqual(rows.iloc[0].change_pct, 4)

    def test_chart_separates_uncovered_gap(self):
        rows = build_overnight_rows(prices(["2026-09-08 19:55", "2026-09-09 04:00"], [111, 112]),
                                    self.daily, self.periods)
        figure = overnight_chart(rows)
        self.assertEqual([trace.name for trace in figure.data], ["After-hours", "Pre-market"])
        self.assertEqual(figure.layout.shapes[0].y0, 110)

    def test_fetch_failure_is_not_a_regular_market_fallback(self):
        fetch_overnight_market.clear()
        with patch("overnight_market.yf.Ticker", side_effect=RuntimeError("unavailable")):
            result = fetch_overnight_market()
        self.assertTrue(result["rows"].empty)
        self.assertIn("unavailable", result["error"])
        fetch_overnight_market.clear()


if __name__ == "__main__":
    unittest.main()