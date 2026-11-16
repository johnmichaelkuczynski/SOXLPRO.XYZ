import unittest
from unittest.mock import patch

import pandas as pd
from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

import stock_chart_api as api


class StockHistoryTests(unittest.TestCase):
    def test_symbols(self):
        self.assertEqual(api.normalize_stock_symbol(" aapl "), "AAPL")
        self.assertEqual(api.normalize_stock_symbol("BRK.B"), "BRK.B")
        for value in ("", "../file", "AAPL?key=x", "<script>", "X" * 31):
            with self.assertRaises(ValueError):
                api.normalize_stock_symbol(value)

    def test_missing_configuration_fails_explicitly(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(api.StockHistoryUnavailable, "EODHD_API_KEY"):
                api.load_stock_history("AAPL")

    def test_existing_eodhd_configuration_is_used(self):
        frame = pd.DataFrame({"Close": [10, 12, float("nan"), -1]},
                             index=pd.date_range("2026-01-01", periods=4))
        with patch.dict("os.environ", {"EODHD_API_KEY": "test-only"}), \
                patch("data_providers.get_custom_benchmark_history", return_value=frame) as history:
            result = api.load_stock_history("BRK.B")
        history.assert_called_once_with("BRK-B.US")
        self.assertEqual(result["source"], "EODHD")
        self.assertEqual(result["prices"], [10, 12])
        self.assertEqual(result["through"], "2026-01-02")

    def test_unknown_symbol_has_explicit_error(self):
        with patch.dict("os.environ", {"EODHD_API_KEY": "test-only"}), \
                patch("data_providers.get_custom_benchmark_history", return_value=pd.DataFrame()):
            with self.assertRaisesRegex(ValueError, "No daily price history"):
                api.load_stock_history("UNKNOWN")


class StockHistoryRouteTests(AsyncHTTPTestCase):
    def get_app(self):
        return Application([(r"/api/chart/stock", api.StockHistory)])

    def setUp(self):
        api._cache.clear()
        api._inflight.clear()
        super().setUp()

    def test_get_stock_and_cache(self):
        payload = {"symbol": "AAPL", "dates": ["2026-01-01", "2026-01-02"],
                   "prices": [10, 11], "source": "test", "through": "2026-01-02"}
        with patch.object(api, "load_stock_history", return_value=payload) as load, \
                patch("benchmark_quotes.read_quotes", return_value={}):
            for _ in range(2):
                response = self.fetch("/api/chart/stock?symbol=aapl")
                self.assertEqual(response.code, 200)
                self.assertIn(b'"symbol": "AAPL"', response.body)
        load.assert_called_once_with("AAPL")

    def test_invalid_symbol_and_provider_failure(self):
        self.assertEqual(self.fetch("/api/chart/stock?symbol=../file").code, 400)
        with patch.object(api, "load_stock_history", side_effect=RuntimeError("private provider detail")):
            response = self.fetch("/api/chart/stock?symbol=AAPL")
        self.assertEqual(response.code, 503)
        self.assertNotIn(b"private provider detail", response.body)
        self.assertIn(b"unavailable", response.body)
