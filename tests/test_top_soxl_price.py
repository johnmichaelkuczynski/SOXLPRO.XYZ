from datetime import datetime, timezone
from inspect import unwrap
from unittest.mock import patch

import pytest
import top_soxl_price
from tiingo_market_data import TiingoError

from top_soxl_price import price_display
from price_labels import public_price_text


def test_newest_quote_wins():
    now = datetime.now(timezone.utc).isoformat()
    price, context = price_display({"quote": {"price": 55.25, "observed_at": now, "source": "Tiingo"}})
    assert price == 55.25
    assert "Schwab" not in context
    assert "Yahoo" not in context


def test_daily_close_never_used_as_fallback():
    assert price_display({"history": {"prices": [51.2], "dates": ["2026-11-13"]}})[0] is None


def test_missing_and_invalid_quotes():
    assert price_display(None)[0] is None
    assert price_display({"quote": {"price": float("nan"), "observed_at": "invalid"}})[0] is None


def test_other_provider_quote_is_not_displayed():
    assert price_display({
        "quote": {"price": 40, "observed_at": "2026-01-01T16:00:00+00:00"},
        "history": {"prices": [51.2], "dates": ["2026-11-13"]},
    })[0] is None


def test_public_errors_do_not_show_provider_names_or_raw_setup_path():
    text = public_price_text(
        "Schwab price unavailable. Authorize at /auth/schwab/connect. Yahoo Finance update failed."
    )
    assert "schwab" not in text.lower()
    assert "yahoo" not in text.lower()
    assert "unavailable" in text
    assert "connection page" in text


@pytest.mark.parametrize("failure", [
    None,
    TiingoError("The owner must authorize price feed at the price-feed connection page."),
    OSError("Token storage cannot be read."),
])
def test_missing_price_does_not_render_warning_banner_or_setup_commentary(failure):
    with patch("live_market_quote.fetch_live_quote") as fetch, \
         patch.object(top_soxl_price, "st") as st:
        if isinstance(failure, Exception):
            fetch.side_effect = failure
        else:
            fetch.return_value = failure
        unwrap(top_soxl_price.render_top_soxl_price)()
        st.error.assert_not_called()
        st.warning.assert_not_called()
        html = st.markdown.call_args.args[0]
        assert "—" in html
        assert "Current price unavailable" not in html
        assert "authorize" not in html
        assert "Token storage" not in html


def test_valid_price_and_timestamp_still_render():
    now = datetime.now(timezone.utc).isoformat()
    with patch("live_market_quote.fetch_live_quote", return_value={
        "source": "Tiingo", "price": 55.25, "observed_at": now,
        "observed_label": "12:00 PM ET", "session": "Regular session",
    }), patch.object(top_soxl_price, "st") as st:
        unwrap(top_soxl_price.render_top_soxl_price)()
        html = st.markdown.call_args.args[0]
        assert "$55.25" in html
        assert "12:00 PM ET" in html
        st.error.assert_not_called()
