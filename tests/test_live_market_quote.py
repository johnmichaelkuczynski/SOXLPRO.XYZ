import unittest
from datetime import datetime, timezone
from unittest.mock import patch, Mock

from live_market_quote import fetch_polygon_quote, parse_polygon_quote, polygon_only


class PolygonQuoteTests(unittest.TestCase):
    def payload(self, stamp):
        return {"status": "OK", "ticker": {"lastTrade": {
            "p": 143.25, "t": int(stamp.timestamp()) * 1_000_000_000},
            "prevDay": {"c": 140}}}

    def test_et_sessions_and_dst(self):
        for month, hour, minute, session, local_time in [
            (7, 13, 29, "Pre-market", "09:29:00 AM"),
            (7, 13, 30, "Regular", "09:30:00 AM"),
            (7, 20, 0, "After-hours", "04:00:00 PM"),
            (1, 14, 29, "Pre-market", "09:29:00 AM"),
            (1, 14, 30, "Regular", "09:30:00 AM"),
            (1, 21, 0, "After-hours", "04:00:00 PM"),
        ]:
            stamp = datetime(2026, month, 5, hour, minute, tzinfo=timezone.utc)
            quote = parse_polygon_quote(self.payload(stamp), now=stamp)
            self.assertEqual(quote["price"], 143.25)
            self.assertEqual(quote["session"], session)
            self.assertIn(local_time, quote["observed_label"])
            self.assertEqual(quote["source"], "Polygon")

    def test_missing_invalid_trade_and_provider_error(self):
        for data in [{"status":"OK","ticker":{}},
                     {"status":"ERROR","error":"Not entitled"},
                     {"ticker":{"lastTrade":{"p":1,"t":1700000000}}},
                     {"ticker":{"lastTrade":{"p":"NaN","t":1700000000000000000}}}]:
            quote = parse_polygon_quote(data)
            self.assertIsNone(quote["price"])
            self.assertTrue(quote["error"])

    @patch.dict("os.environ", {"POLYGON_API_KEY":"test-key"})
    @patch("live_market_quote.requests.get")
    def test_http_error_text_and_exact_request(self, get):
        get.return_value = Mock(ok=False,status_code=403)
        get.return_value.json.return_value = {"error":"Subscription does not include last trades"}
        quote = fetch_polygon_quote()
        self.assertIn("Subscription does not include last trades",quote["error"])
        self.assertIsNone(quote["price"])
        self.assertEqual(get.call_args.args[0],
            "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/SOXL")
        self.assertEqual(get.call_args.kwargs["params"], {"apiKey":"test-key"})

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_key_and_legacy_quote_never_fall_back(self):
        self.assertIn("POLYGON_API_KEY",fetch_polygon_quote()["error"])
        self.assertIsNone(polygon_only({"source":"Robinhood","price":100})["price"])

    def test_snapshot_no_daily_close_fallback(self):
        import pandas as pd
        from top_market_snapshot import compute_market_snapshot
        result = compute_market_snapshot(
            pd.DataFrame({"Close":[100]},index=pd.to_datetime(["2026-01-01"])),
            quote={"source":"Polygon","error":"No lastTrade","price":None})
        self.assertIsNone(result["current_price"])
        self.assertEqual(result["error"], "No lastTrade")


if __name__ == "__main__":
    unittest.main()
