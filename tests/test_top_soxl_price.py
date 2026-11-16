from datetime import datetime, timezone

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
