from datetime import datetime, timezone

from top_soxl_price import price_display


def test_newest_quote_wins():
    now = datetime.now(timezone.utc).isoformat()
    price, context = price_display({
        "quote": {"price": 40, "observed_at": "2026-01-01T16:00:00+00:00"},
        "market_feed": {"quote": {"price": 55.25, "observed_at": now, "source": "Schwab"}},
    })
    assert price == 55.25
    assert "Schwab" in context


def test_daily_close_fallback():
    assert price_display({"history": {"prices": [51.2], "dates": ["2026-11-13"]}}) == (
        51.2, "Last available daily close · 2026-11-13 · Not a live quote")


def test_missing_and_invalid_quotes():
    assert price_display(None)[0] is None
    assert price_display({"quote": {"price": float("nan"), "observed_at": "invalid"}})[0] is None


def test_newer_daily_history_beats_old_quote():
    assert price_display({
        "quote": {"price": 40, "observed_at": "2026-01-01T16:00:00+00:00"},
        "history": {"prices": [51.2], "dates": ["2026-11-13"]},
    })[0] == 51.2
