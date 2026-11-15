"""Owner-authorized Schwab market data. No account or trading endpoints.

Tokens are shared by the gateway and workers using a private, locked file.
On Coolify, put SCHWAB_TOKEN_FILE on a persistent volume.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from zoneinfo import ZoneInfo

import requests

TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
MARKET_URL = "https://api.schwabapi.com/marketdata/v1"
DEFAULT_CALLBACK = "https://soxl.ai/auth/schwab/callback"


class SchwabError(ValueError):
    """Only sanitized, user-safe error messages may be raised."""


class AuthorizationRejected(SchwabError):
    pass


def configured():
    return bool(os.environ.get("SCHWAB_CLIENT_ID") and
                os.environ.get("SCHWAB_CLIENT_SECRET"))


def redirect_uri():
    return os.environ.get("SCHWAB_REDIRECT_URI", DEFAULT_CALLBACK).strip()


def token_path():
    return Path(os.environ.get("SCHWAB_TOKEN_FILE", "/tmp/soxl-schwab/tokens.json"))


def _fingerprint():
    return hashlib.sha256(os.environ.get("SCHWAB_CLIENT_ID", "").encode()).hexdigest()


@contextmanager
def _locked():
    path = token_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        deadline = time.monotonic() + 12
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise SchwabError("Schwab authorization is busy; retry shortly.") from None
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)


def _read():
    try:
        # Tokens from a different developer app must never be reused.
        with token_path().open() as handle:
            value = json.load(handle)
        return value if value.get("app") == _fingerprint() else {}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def _write(value):
    path = token_path()
    fd, temporary = tempfile.mkstemp(prefix=".schwab-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def status():
    """Never return tokens, client IDs, account IDs, or provider response bodies."""
    if not configured():
        return {"state": "not_configured", "message": "Schwab app keys are not configured."}
    data = _read()
    if not data.get("refresh_token"):
        return {"state": "authorization_required",
                "message": "Schwab keys are saved. The owner must authorize market-data access."}
    if data.get("reauthorize"):
        return {"state": "authorization_required",
                "message": "Schwab authorization expired or was revoked. The owner must reconnect."}
    return {"state": "authorized", "message": "Schwab authorization is saved.",
            "authorized_at": data.get("authorized_at")}


def _token_request(form):
    try:
        response = requests.post(
            TOKEN_URL, data=form,
            auth=(os.environ["SCHWAB_CLIENT_ID"], os.environ["SCHWAB_CLIENT_SECRET"]),
            timeout=8, allow_redirects=False)
        if response.status_code in (400, 401, 403):
            raise AuthorizationRejected("Schwab rejected authorization. Reconnect and check the app's approval and keys.")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data.get("access_token"), str) or not data["access_token"]:
            raise ValueError()
        expiry = float(data["expires_in"])
        if not math.isfinite(expiry) or expiry <= 0:
            raise ValueError()
        data["expires_at"] = time.time() + expiry
        return data
    except SchwabError:
        raise
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
        raise SchwabError("Schwab's authorization service is unavailable or returned invalid data.") from None


def exchange_code(code):
    if not configured():
        raise SchwabError("Schwab app keys are not configured.")
    with _locked():
        value = _token_request({"grant_type": "authorization_code", "code": code,
                                "redirect_uri": redirect_uri()})
        if not value.get("refresh_token"):
            raise SchwabError("Schwab did not return a refresh token. Reconnect.")
        value.update(app=_fingerprint(), authorized_at=datetime.now(timezone.utc).isoformat())
        _write(value)


def access_token():
    if not configured():
        raise SchwabError("Schwab app keys are not configured.")
    with _locked():
        value = _read()
        if not value.get("refresh_token") or value.get("reauthorize"):
            raise SchwabError("The owner must authorize Schwab at /auth/schwab/connect.")
        if value.get("access_token") and float(value.get("expires_at", 0)) > time.time() + 60:
            return value["access_token"]
        if value.get("retry_after", 0) > time.time():
            raise SchwabError("Schwab authorization is temporarily unavailable; retry shortly.")
        try:
            refreshed = _token_request({"grant_type": "refresh_token",
                                        "refresh_token": value["refresh_token"]})
        except SchwabError as exc:
            # Preserve the refresh token after temporary failures, but avoid
            # hammering Schwab from every benchmark worker.
            value["retry_after"] = time.time() + 60
            # Only an actual rejection requires renewed owner consent.
            if isinstance(exc, AuthorizationRejected):
                value["reauthorize"] = True
            _write(value)
            raise
        value.update(refreshed)
        value.pop("retry_after", None)
        _write(value)
        return value["access_token"]


def _get(path, params):
    token = access_token()
    try:
        response = requests.get(MARKET_URL + path, params=params,
                                headers={"Authorization": "Bearer " + token}, timeout=8,
                                allow_redirects=False)
        if response.status_code == 401:
            with _locked():
                value = _read()
                if value.get("access_token") == token:
                    value["expires_at"] = 0
                    _write(value)
            raise SchwabError("Schwab rejected its access token; a refresh will be attempted on the next check.")
        if response.status_code == 403:
            raise SchwabError("Schwab denied market-data access. Check market-data entitlements.")
        if response.status_code == 429:
            raise SchwabError("Schwab's market-data rate limit was reached.")
        response.raise_for_status()
        return response.json()
    except SchwabError:
        raise
    except (requests.RequestException, ValueError):
        raise SchwabError("Schwab market data is temporarily unavailable.") from None


def _timestamp(milliseconds):
    try:
        stamp = float(milliseconds) / 1000
        if stamp <= 0 or stamp > time.time() + 60:
            return None
        return datetime.fromtimestamp(stamp, timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def parse_quote(payload, symbol, *, strict_session=False, now=None):
    item = payload.get(symbol) or {}
    now = now or datetime.now(timezone.utc)
    candidates = []
    fields = (
        ("regular", "regularMarketLastPrice", "regularMarketTradeTime", True),
        ("quote", "lastPrice", "tradeTime", False),
        ("extended", "lastPrice", "tradeTime", False),
    )
    if strict_session:
        local = now.astimezone(ZoneInfo("America/New_York"))
        minutes = local.hour * 60 + local.minute
        section = "quote" if local.weekday() < 5 and 570 <= minutes < 960 else "extended"
        fields = ((section, "lastPrice", "tradeTime", section == "quote"),)
    for section, price_field, time_field, regular in fields:
        values = item.get(section) or {}
        try:
            price = float(values.get(price_field))
        except (ValueError, TypeError):
            continue
        observed = _timestamp(values.get(time_field))
        if not observed or not math.isfinite(price) or price <= 0:
            continue
        dt = datetime.fromisoformat(observed)
        minute = dt.astimezone(ZoneInfo("America/New_York"))
        minutes = minute.hour * 60 + minute.minute
        session = ("REGULAR" if regular or 570 <= minutes < 960 else
                   "PRE" if 240 <= minutes < 570 else
                   "POST" if 960 <= minutes < 1200 else "OVERNIGHT")
        candidates.append({"price": price, "observed_at": observed, "state": session})
    if not candidates:
        raise SchwabError("Schwab returned no timestamped trade price for this symbol.")
    result = max(candidates, key=lambda value: value["observed_at"])
    dt = datetime.fromisoformat(result["observed_at"])
    delayed = item.get("realtime") is False
    result.update(
        source="Schwab",
        currency="USD", delayed=delayed,
        extended=result["state"] != "REGULAR",
        session={"REGULAR": "Regular session", "PRE": "Pre-market",
                 "POST": "After-hours", "OVERNIGHT": "Overnight"}[result["state"]],
        stale=(now - dt).total_seconds() > 900,
        observed_label=dt.astimezone(ZoneInfo("America/New_York")).strftime("%b %d, %Y %I:%M:%S %p ET"),
        checked_at=now.isoformat(), prev_close=(item.get("quote") or {}).get("closePrice"),
        feed_warning="Schwab labels this quote delayed." if delayed else "")
    return result


def fetch_quote(symbol="SOXL"):
    # Schwab does not provide spot BTC-USD. Retain the existing crypto provider.
    mapped = {"VIX": "$VIX", "SOX": "$SOX"}.get(symbol, symbol)
    if symbol == "BTC":
        raise SchwabError("Use the existing crypto feed for BTC.")
    try:
        params = {"symbols": mapped}
        if symbol == "SOXL":
            params["fields"] = "quote,extended"
        return parse_quote(_get("/quotes", params), mapped, strict_session=symbol == "SOXL")
    except (KeyError, TypeError, AttributeError, OSError):
        raise SchwabError("Schwab returned an invalid quote or its token storage is unavailable.") from None


def load_option_chain(expiration, kind):
    payload = _get("/chains", {"symbol": "SOXL", "contractType": kind.upper(),
                               "strategy": "SINGLE", "includeUnderlyingQuote": "true",
                               "fromDate": expiration.isoformat(), "toDate": expiration.isoformat()})
    if not isinstance(payload, dict) or payload.get("status") != "SUCCESS":
        raise SchwabError("Schwab could not supply the SOXL options chain.")
    underlying = payload.get("underlying") or {}
    spot_time = _timestamp(underlying.get("tradeTime"))
    rows = []
    key = "callExpDateMap" if kind == "call" else "putExpDateMap"
    for expiry_key, strikes in (payload.get(key) or {}).items():
        if expiry_key.split(":")[0] != expiration.isoformat():
            continue
        for contracts in strikes.values():
            for contract in contracts:
                iv = contract.get("volatility")
                try:
                    iv = float(iv) / 100
                    if not math.isfinite(iv) or iv <= 0:
                        iv = None
                except (TypeError, ValueError):
                    iv = None
                rows.append(dict(
                    ticker=contract.get("symbol"), strike=contract.get("strikePrice"),
                    expiration=expiration.isoformat(), type=kind,
                    multiplier=contract.get("multiplier"),
                    bid=contract.get("bid"), ask=contract.get("ask"), iv=iv,
                    quote_time=_timestamp(contract.get("quoteTimeInLong")),
                    spot=underlying.get("last"), spot_time=spot_time,
                    adjusted=bool(contract.get("nonStandard") or contract.get("optionDeliverablesList")),
                    source="Schwab", delayed=payload.get("isDelayed")))
    if not rows:
        raise SchwabError("Schwab returned no contracts for that expiration and option type.")
    return sorted(rows, key=lambda row: float(row.get("strike") or 0))
