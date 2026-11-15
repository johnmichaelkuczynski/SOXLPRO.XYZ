from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from live_market_quote import fetch_live_quote
from schwab_market_data import parse_quote, fetch_quote, SchwabError


def payload():
    return {"SOXL": {
        "quote": {"lastPrice": 50, "tradeTime": 1794596400000},
        "extended": {"lastPrice": 52, "tradeTime": 1794603600000},
    }}


@pytest.mark.parametrize("hour,section,price", [(15, "quote", 50), (22, "extended", 52), (2, "extended", 52)])
def test_session_selects_exact_fields(hour, section, price):
    now = datetime(2026, 11, 16, hour, tzinfo=timezone.utc)
    data = payload()
    quote = parse_quote(data, "SOXL", strict_session=True, now=now)
    assert quote["price"] == price
    assert quote["source"] == "Schwab"
    assert quote["observed_at"] == datetime.fromtimestamp(
        data["SOXL"][section]["tradeTime"] / 1000, timezone.utc).isoformat()


def test_extended_missing_is_error_not_regular_fallback():
    data = payload()
    del data["SOXL"]["extended"]
    with pytest.raises(SchwabError):
        parse_quote(data, "SOXL", strict_session=True,
                    now=datetime(2026, 11, 16, 22, tzinfo=timezone.utc))


def test_exact_request_parameters():
    with patch("schwab_market_data._get", return_value=payload()) as get, \
            patch("schwab_market_data.parse_quote", return_value={"source": "Schwab"}) as parse:
        fetch_quote()
    get.assert_called_once_with("/quotes", {"symbols": "SOXL", "fields": "quote,extended"})
    assert parse.call_args.kwargs["strict_session"] is True


def test_failure_never_calls_another_provider():
    with patch("schwab_market_data.fetch_quote", side_effect=SchwabError("Unavailable")) as quote:
        with pytest.raises(SchwabError):
            fetch_live_quote.__wrapped__()
    quote.assert_called_once_with("SOXL")
