from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from tiingo_market_data import TiingoError, fetch_quote, parse_quote

NOW = datetime(2026, 11, 16, 16, 49, 15, tzinfo=timezone.utc)
ROW = {"ticker": "SOXL", "tngoLast": 51.14,
       "timestamp": "2026-11-16T11:49:10.525746659-05:00",
       "last": None, "lastSaleTimestamp": None, "prevClose": 58.32}


def test_reference_quote_works_without_iex_trade_entitlement():
    quote = parse_quote([ROW], now=NOW)
    assert quote["price"] == 51.14
    assert quote["source"] == "Tiingo"
    assert quote["price_kind"] == "reference"
    assert quote["state"] == "REGULAR"
    assert quote["observed_at"] == "2026-11-16T16:49:10.525746+00:00"
    assert not quote["stale"]


@pytest.mark.parametrize("changes", [
    {"tngoLast": None}, {"tngoLast": 0}, {"tngoLast": float("nan")},
    {"timestamp": None}, {"timestamp": "2026-11-16T16:49:10"},
    {"timestamp": "2027-01-01T00:00:00Z"}, {"ticker": "AAPL"},
])
def test_rejects_invalid_quotes_without_using_previous_close(changes):
    with pytest.raises(TiingoError):
        parse_quote([{**ROW, **changes}], now=NOW)


def test_failure_uses_safe_error_and_not_a_fallback():
    with patch.dict("os.environ", {"TIINGO_API_KEY": "test-only-key"}), patch(
        "tiingo_market_data.requests.get", return_value=Mock(status_code=429)
    ) as request:
        with pytest.raises(TiingoError, match="limit"):
            fetch_quote()
        assert request.call_count == 1
        assert request.call_args.kwargs["headers"] == {"Authorization": "Token test-only-key"}
        assert "params" not in request.call_args.kwargs
