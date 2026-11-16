"""Owner-key Tiingo quotes with explicit timestamps and no historical fallback."""
import math
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests


class TiingoError(RuntimeError):
    pass


def parse_quote(payload, symbol="SOXL", *, now=None):
    now = now or datetime.now(timezone.utc)
    ticker = symbol.upper().removesuffix(".US")
    rows = payload if isinstance(payload, list) else []
    for item in rows:
        if not isinstance(item, dict) or str(item.get("ticker", "")).upper() != ticker:
            continue
        # tngoLast is Tiingo's documented reference price. Entitlement-only
        # IEX trade fields can legitimately be null on this account.
        for field, stamp_field, kind in (
            ("tngoLast", "timestamp", "reference"),
            ("last", "lastSaleTimestamp", "trade"),
        ):
            try:
                raw = item.get(field)
                if isinstance(raw, bool):
                    continue
                price = float(raw)
                stamp = datetime.fromisoformat(str(item.get(stamp_field)).replace("Z", "+00:00"))
                if stamp.tzinfo is None or not math.isfinite(price) or price <= 0:
                    continue
                if (stamp - now).total_seconds() > 60:
                    continue
            except (TypeError, ValueError, OverflowError):
                continue
            local = stamp.astimezone(ZoneInfo("America/New_York"))
            minutes = local.hour * 60 + local.minute
            state = ("CLOSED" if local.weekday() >= 5 else
                     "REGULAR" if 570 <= minutes < 960 else
                     "PRE" if 240 <= minutes < 570 else
                     "POST" if 960 <= minutes < 1200 else "OVERNIGHT")
            return {
                "price": price, "source": "Tiingo", "currency": "USD",
                "price_kind": kind, "observed_at": stamp.astimezone(timezone.utc).isoformat(),
                "observed_label": local.strftime("%b %d, %Y %I:%M:%S %p ET"),
                "state": state, "session": {
                    "REGULAR": "Regular session", "PRE": "Pre-market",
                    "POST": "After-hours", "OVERNIGHT": "Overnight", "CLOSED": "Market closed",
                }[state],
                "extended": state != "REGULAR", "delayed": bool(item.get("delayed", False)),
                "stale": (now - stamp).total_seconds() > 900,
                "checked_at": now.isoformat(), "prev_close": item.get("prevClose"),
                "feed_warning": "",
            }
    raise TiingoError("The price feed returned no valid timestamped price.")


def fetch_quote(symbol="SOXL"):
    ticker = symbol.upper().removesuffix(".US")
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,19}", ticker):
        raise TiingoError("Invalid stock symbol.")
    key = os.environ.get("TIINGO_API_KEY")
    if not key:
        raise TiingoError("The price-feed API key is not configured.")
    try:
        response = requests.get(
            "https://api.tiingo.com/iex/" + ticker.lower(),
            headers={"Authorization": "Token " + key},
            timeout=12, allow_redirects=False,
        )
    except requests.RequestException:
        raise TiingoError("The price feed is temporarily unavailable.") from None
    if response.status_code in (401, 403):
        raise TiingoError("The price-feed request was not authorized.")
    if response.status_code == 429:
        raise TiingoError("The price-feed request limit has been reached.")
    if response.status_code != 200:
        raise TiingoError("The price feed could not return this symbol.")
    try:
        payload = response.json()
    except ValueError:
        raise TiingoError("The price feed returned an invalid response.") from None
    return parse_quote(payload, ticker)
