import unittest
from unittest.mock import patch, Mock
from datetime import datetime, timezone
from benchmark_quotes import valid_quote, fetch_quote, refresh_one


class BenchmarkQuotesTest(unittest.TestCase):
    def test_invalid_quotes(self):
        for price in (float("nan"), float("inf"), -1, 0):
            with self.assertRaises(ValueError):
                valid_quote(price, 1700000000, "USD", "test")
        with self.assertRaises(ValueError):
            valid_quote(1, datetime.now(timezone.utc).timestamp()+600, "USD", "test")

    @patch("requests.get")
    def test_latest_observation_and_index_units(self, get):
        get.return_value = Mock()
        get.return_value.json.return_value = {"chart": {"result": [{
            "meta": {"regularMarketTime": 1700000000, "regularMarketPrice": 18, "currency": "USD"},
            "timestamp": [1700000060, 1700000120],
            "indicators": {"quote": [{"close": [19, None]}]}
        }]}}
        quote = fetch_quote("VIX")
        self.assertEqual(quote["price"], 19)
        self.assertEqual(quote["unit"], "points")
        self.assertEqual(quote["observed_at"], datetime.fromtimestamp(1700000060,timezone.utc).isoformat())

    @patch("benchmark_quotes.query")
    @patch("benchmark_quotes.fetch_quote", side_effect=TimeoutError())
    def test_failure_retains_payload(self, fetch, query):
        refresh_one("QQQ")
        sql, params = query.call_args.args
        self.assertNotIn("payload=", sql)
        self.assertEqual(params, ("QQQ", "TimeoutError"))


if __name__ == "__main__":
    unittest.main()
