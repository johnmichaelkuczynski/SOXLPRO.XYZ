import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from live_market_quote import select_quote, fetch_live_quote


class LiveQuoteTests(unittest.TestCase):
    now = datetime(2026, 10, 10, 3, tzinfo=timezone.utc)
    yahoo = dict(regularMarketPrice=140, regularMarketTime=1791576001,
                 regularMarketPreviousClose=142, marketState="CLOSED",
                 postMarketPrice=139.43, postMarketTime=1791590391)

    def test_closed_market_uses_newer_after_hours(self):
        quote = select_quote(self.yahoo, {}, self.now)
        self.assertEqual(quote["price"], 139.43)
        self.assertEqual(quote["state"], "POST")
        self.assertEqual(quote["prev_close"], 140)
        self.assertTrue(quote["stale"])

    def test_actual_overnight_trade_selected(self):
        rh = dict(last_non_reg_trade_price="141.25",
                  venue_last_non_reg_trade_time="2026-10-10T02:59:00Z")
        quote = select_quote(self.yahoo, rh, self.now)
        self.assertEqual(quote["state"], "OVERNIGHT")
        self.assertEqual(quote["source"], "Robinhood")
        self.assertEqual(quote["prev_close"], 140)
        self.assertFalse(quote["stale"])

    def test_updated_at_is_not_a_trade_timestamp(self):
        rh = dict(last_non_reg_trade_price="145", updated_at="2026-10-10T03:00:00Z")
        self.assertEqual(select_quote(self.yahoo, rh, self.now)["source"], "Yahoo Finance")

    def test_invalid_or_future_quotes_ignored(self):
        for price, timestamp in [("NaN", "2026-10-10T02:59:00Z"),
                                 (-3, "2026-10-10T02:59:00Z"),
                                 (145, "2026-10-11T03:00:00Z"),
                                 (145, None), (145, "bad"),
                                 (145, "2026-10-10T02:59:00")]:
            with self.subTest(price=price, timestamp=timestamp):
                self.assertIsNone(select_quote({}, dict(
                    last_non_reg_trade_price=price,
                    venue_last_non_reg_trade_time=timestamp), self.now))

    def test_older_robinhood_quote_does_not_override_newer_yahoo(self):
        rh = dict(last_non_reg_trade_price="139.50",
                  venue_last_non_reg_trade_time="2026-10-09T23:59:28.255906418Z")
        self.assertEqual(select_quote(self.yahoo, rh, self.now)["price"], 139.43)

    def test_premarket_classification(self):
        now = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
        rh = dict(last_non_reg_trade_price="141", venue_last_non_reg_trade_time=now.isoformat())
        self.assertEqual(select_quote(self.yahoo, rh, now)["state"], "PRE")

    def test_robinhood_previous_close_is_numeric_or_unavailable(self):
        for previous, expected in [("142.52", 142.52), ("bad", None), ("NaN", None)]:
            rh = dict(last_trade_price="140", venue_last_trade_time=self.now.isoformat(),
                      previous_close=previous)
            quote = select_quote({}, rh, self.now)
            self.assertEqual(quote["prev_close"], expected)

    def test_provider_failure_preserves_other_quote_and_reports_warning(self):
        with patch("live_market_quote.yf.Ticker") as ticker, patch(
                "live_market_quote.requests.get", side_effect=RuntimeError("offline")):
            ticker.return_value.info = self.yahoo
            quote = fetch_live_quote.__wrapped__()
        self.assertEqual(quote["source"], "Yahoo Finance")
        self.assertIn("Robinhood", quote["feed_warning"])


if __name__ == "__main__":
    unittest.main()
