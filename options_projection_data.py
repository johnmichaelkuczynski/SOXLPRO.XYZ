"""On-demand Polygon options snapshots; no fabricated or stale fallback quotes."""
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests
import streamlit as st


class OptionsDataError(ValueError):
    pass


def stamp(value):
    if not value:
        return None
    return datetime.fromtimestamp(float(value) / 1e9, timezone.utc).isoformat()


@st.cache_data(ttl=60, show_spinner=False)
def load_chain(expiration, kind):
    key = os.environ.get("POLYGON_API_KEY")
    if not key:
        raise OptionsDataError(
            "Options data is not connected. Add POLYGON_API_KEY in workspace Secrets "
            "with access to options snapshots and bid/ask quotes, then refresh."
        )
    if kind not in ("call", "put"):
        raise OptionsDataError("Select a call or put.")
    url = "https://api.polygon.io/v3/snapshot/options/SOXL"
    params = {"expiration_date": expiration.isoformat(), "contract_type": kind,
              "limit": 250}
    rows = []
    try:
        for _ in range(20):
            response = requests.get(url, params=params,
                                    headers={"Authorization": "Bearer " + key}, timeout=15)
            if response.status_code in (401, 403):
                raise OptionsDataError("Polygon rejected access. Check the API key and options/quote entitlements.")
            if response.status_code == 429:
                raise OptionsDataError("Polygon rate limit reached. Wait a minute before retrying.")
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") in ("ERROR", "NOT_AUTHORIZED"):
                raise OptionsDataError("Polygon could not supply this options chain.")
            for obj in payload.get("results", []):
                d, q, u = (obj.get(x) or {} for x in ("details", "last_quote", "underlying_asset"))
                rows.append(dict(
                    ticker=d.get("ticker"), strike=d.get("strike_price"),
                    expiration=d.get("expiration_date"), type=d.get("contract_type"),
                    multiplier=d.get("shares_per_contract", 100),
                    bid=q.get("bid"), ask=q.get("ask"), iv=obj.get("implied_volatility"),
                    quote_time=stamp(q.get("last_updated")),
                    spot=u.get("price"), spot_time=stamp(u.get("last_updated")),
                    adjusted=bool(d.get("additional_underlyings")),
                ))
            url = payload.get("next_url")
            if not url:
                break
            if urlsplit(url).hostname != "api.polygon.io" or not url.startswith("https://"):
                raise OptionsDataError("Unexpected provider pagination address.")
            params = None
        else:
            raise OptionsDataError("Chain exceeds the safe page limit; select another expiration.")
    except OptionsDataError:
        raise
    except (requests.RequestException, ValueError, TypeError, OverflowError):
        raise OptionsDataError("Options provider unavailable or returned invalid data. Please retry.") from None
    if not rows:
        raise OptionsDataError("No contracts found for that expiration and option type.")
    return sorted(rows, key=lambda r: float(r.get("strike") or 0))
