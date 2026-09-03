import unittest
from unittest.mock import patch

import pandas as pd

from data_providers import (
    get_custom_benchmark_history,
    normalize_eodhd_symbol,
)


class CustomBenchmarkTests(unittest.TestCase):
    def test_plain_ticker_defaults_to_us_exchange(self):
        self.assertEqual(normalize_eodhd_symbol(" sbr "), "SBR.US")
        self.assertEqual(normalize_eodhd_symbol("pll"), "PLL.US")

    def test_explicit_eodhd_exchange_is_preserved(self):
        self.assertEqual(normalize_eodhd_symbol("vod.lse"), "VOD.LSE")
        self.assertEqual(normalize_eodhd_symbol("vix.indx"), "VIX.INDX")

    def test_invalid_or_empty_symbols_are_rejected(self):
        for symbol in ("", "   ", "../../secret", "SBR?token=x", "A" * 31):
            with self.assertRaises(ValueError):
                normalize_eodhd_symbol(symbol)

    @patch("data_providers.get_equity_history")
    def test_custom_history_uses_adjusted_close_and_exchange(self, history):
        index = pd.to_datetime(["2026-09-01", "2026-09-02"])
        history.return_value = pd.DataFrame(
            {"close": [10.0, 11.0], "adj_close": [9.5, 10.5]},
            index=index,
        )

        result = get_custom_benchmark_history.__wrapped__("vod.lse")

        history.assert_called_once_with("VOD", suffix=".LSE")
        self.assertEqual(result["Close"].tolist(), [9.5, 10.5])


if __name__ == "__main__":
    unittest.main()