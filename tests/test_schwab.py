"""No real credentials, account consent, provider calls, or token files."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import date
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import re
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlencode, urlsplit

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

import schwab_market_data as provider
import schwab_auth as auth


class MemoryStore:
    """Test double only; production always uses PostgreSQL."""
    def __init__(self):
        self.rows = {}
        self.lock = threading.RLock()

    def read(self, app):
        with self.lock:
            return deepcopy(self.rows.get(app, {}))

    @contextmanager
    def locked(self, app):
        with self.lock:
            store = self
            class Record:
                def read(self):
                    return store.read(app)

                def write(self, value):
                    store.rows[app] = deepcopy(value)
            yield Record()


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "SCHWAB_CLIENT_ID": "test-client", "SCHWAB_CLIENT_SECRET": "test-secret",
            "DATABASE_URL": "postgresql://test-only"}, clear=True)
        self.env.start()
        self.store = MemoryStore()
        self.addCleanup(patch.stopall)
        patch.object(provider.token_store, "locked", self.store.locked).start()
        patch.object(provider.token_store, "read", self.store.read).start()

    def tearDown(self):
        self.env.stop()

    def save(self, **overrides):
        value = dict(app=provider._fingerprint(), access_token="test-access",
                     refresh_token="test-refresh", expires_at=time.time() + 1800,
                     refresh_expires_at=time.time() + 6 * 86400,
                     authorized_at="2026-11-15T00:00:00+00:00")
        value.update(overrides)
        with provider._locked() as record:
            record.write(value)

    def test_keys_without_owner_authorization_make_no_network_request(self):
        with patch.object(provider.requests, "post") as post:
            self.assertEqual(provider.status()["state"], "authorization_required")
            with self.assertRaises(provider.SchwabError):
                provider.access_token()
            post.assert_not_called()

    def test_missing_keys_are_lazy(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(provider.configured())
            self.assertEqual(provider.status()["state"], "not_configured")

    def test_credentials_are_trimmed_and_read_at_runtime(self):
        with patch.dict(os.environ, {"SCHWAB_CLIENT_ID": " \ttest-client\n",
                                     "SCHWAB_CLIENT_SECRET": " \ttest-secret\r\n"}):
            self.assertTrue(provider.configured())
            response = Mock(status_code=200)
            response.json.return_value = dict(access_token="new-access", expires_in=1800)
            with patch.object(provider.requests, "post", return_value=response) as post:
                provider._token_request({"grant_type": "authorization_code", "code": "test-code"})
            self.assertEqual(post.call_args.kwargs["auth"], ("test-client", "test-secret"))
            os.environ["SCHWAB_CLIENT_SECRET"] = "replacement"
            self.assertEqual(provider.client_secret(), "replacement")
            os.environ["SCHWAB_CLIENT_SECRET"] = " \r\n"
            self.assertFalse(provider.configured())

    def test_valid_token_reused_and_status_private(self):
        self.save()
        with patch.object(provider.requests, "post") as post:
            self.assertEqual(provider.access_token(), "test-access")
            post.assert_not_called()
        status = json.dumps(provider.status())
        self.assertNotIn("test-access", status)
        self.assertNotIn("test-refresh", status)
        self.assertNotIn("test-client", status)

    def test_expired_access_token_refreshes_and_rotated_token_is_persisted(self):
        self.save(expires_at=0)
        response = Mock(status_code=200)
        response.json.return_value = dict(access_token="new-access", refresh_token="rotated", expires_in=1800)
        with patch.object(provider.requests, "post", return_value=response) as post:
            self.assertEqual(provider.access_token(), "new-access")
            self.assertEqual(post.call_args.kwargs["data"]["grant_type"], "refresh_token")
            self.assertEqual(post.call_args.kwargs["auth"], ("test-client", "test-secret"))
        self.assertEqual(provider._read()["refresh_token"], "rotated")
        self.assertEqual(provider.status()["authorized_at"], "2026-11-15T00:00:00+00:00")

    def test_rejected_refresh_requires_reauthorization(self):
        self.save(expires_at=0)
        response = Mock(status_code=400)
        response.json.return_value = {"error": "invalid_grant"}
        with patch.object(provider.requests, "post", return_value=response):
            with self.assertRaises(provider.SchwabError):
                provider.access_token()
        self.assertEqual(provider.status()["state"], "authorization_required")

    def test_five_minute_refresh_threshold_before_market_request(self):
        self.save(expires_at=time.time() + 240)
        response = Mock(status_code=200)
        response.json.return_value = {}
        with patch.object(provider, "_token_request", return_value={
                "access_token": "fresh-access", "expires_at": time.time() + 1800}) as refresh, \
                patch.object(provider.requests, "get", return_value=response) as get:
            provider._get("/quotes", {"symbols": "SOXL"})
        refresh.assert_called_once()
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer fresh-access")
        self.assertEqual(provider._read()["refresh_token"], "test-refresh")

    def test_refresh_does_not_extend_seven_day_expiry(self):
        deadline = time.time() + 600
        self.save(expires_at=0, refresh_expires_at=deadline)
        with patch.object(provider, "_token_request", return_value={
                "access_token": "fresh-access", "refresh_token": "rotated",
                "expires_at": time.time() + 1800, "refresh_token_expires_in": 604800}):
            provider.access_token()
        self.assertEqual(provider._read()["refresh_expires_at"], deadline)

    def test_expired_refresh_token_requires_consent_without_a_network_call(self):
        self.save(refresh_expires_at=time.time() - 1)
        with patch.object(provider, "_token_request") as refresh:
            with self.assertRaisesRegex(provider.SchwabError, "/auth/schwab/connect"):
                provider.access_token()
        refresh.assert_not_called()
        self.assertEqual(provider.status()["state"], "authorization_required")

    def test_temporary_refresh_failure_retains_consent_and_saves_cooldown(self):
        self.save(expires_at=0)
        with patch.object(provider, "_token_request",
                          side_effect=provider.SchwabError("Temporarily unavailable")) as refresh:
            with self.assertRaises(provider.SchwabError):
                provider.access_token()
            with self.assertRaises(provider.SchwabError):
                provider.access_token()
        refresh.assert_called_once()
        self.assertFalse(provider._read().get("reauthorize"))
        self.assertEqual(provider._read()["refresh_token"], "test-refresh")
        self.assertEqual(provider.status()["state"], "authorized")

    def test_invalid_app_credentials_do_not_revoke_refresh_token(self):
        self.save(expires_at=0)
        response = Mock(status_code=401)
        response.json.return_value = {"error": "invalid_client"}
        with patch.object(provider.requests, "post", return_value=response):
            with self.assertRaisesRegex(provider.SchwabError, "app credentials"):
                provider.access_token()
        self.assertFalse(provider._read().get("reauthorize"))
        self.assertEqual(provider.status()["state"], "authorized")

    def test_storage_outage_is_not_reported_as_missing_authorization(self):
        with patch.object(provider.token_store, "read",
                          side_effect=provider.token_store.TokenStorageError("Database unavailable")):
            state = provider.status()
        self.assertEqual(state["state"], "storage_unavailable")
        self.assertNotIn("authorize", state["message"])

    def test_quote_timestamp_is_trade_time_not_quote_time(self):
        now = int(time.time() * 1000)
        data = {"SOXL": {"realtime": False, "quote": {
            "lastPrice": 50.25, "tradeTime": now - 120000, "quoteTime": now}}}
        quote = provider.parse_quote(data, "SOXL")
        self.assertEqual(quote["price"], 50.25)
        self.assertTrue(quote["delayed"])
        self.assertEqual(quote["source"], "Schwab")
        self.assertEqual(quote["observed_at"], provider._timestamp(now - 120000))
        del data["SOXL"]["quote"]["tradeTime"]
        with self.assertRaises(provider.SchwabError):
            provider.parse_quote(data, "SOXL")

    def test_invalid_prices_never_returned(self):
        for price in [float("nan"), 0, -1, "invalid"]:
            with self.subTest(price=price), self.assertRaises(provider.SchwabError):
                provider.parse_quote({"SOXL": {"quote": {
                    "lastPrice": price, "tradeTime": time.time() * 1000}}}, "SOXL")

    def test_options_normalize_iv_and_preserve_missing_values(self):
        expiry = date(2027, 1, 15)
        payload = dict(status="SUCCESS", isDelayed=True, underlying={"last": 50},
                       callExpDateMap={"2027-01-15:61": {"55": [{
                           "symbol": "TEST-OPTION", "strikePrice": 55, "bid": 2, "ask": 2.2,
                           "volatility": 125, "multiplier": 100,
                           "quoteTimeInLong": time.time() * 1000}]}})
        with patch.object(provider, "_get", return_value=payload):
            rows = provider.load_option_chain(expiry, "call")
        self.assertEqual(rows[0]["iv"], 1.25)
        self.assertIsNone(rows[0]["spot_time"])
        self.assertEqual(rows[0]["source"], "Schwab")
        self.assertTrue(rows[0]["delayed"])

    def test_quote_integration_uses_schwab_only(self):
        from live_market_quote import fetch_live_quote
        quote = dict(price=50, stale=False, source="Schwab")
        with patch.object(provider, "fetch_quote", return_value=quote):
            self.assertEqual(fetch_live_quote.__wrapped__(), quote)

    def test_options_integration_uses_schwab_first(self):
        from options_projection_data import load_chain
        with patch.object(provider, "load_option_chain", return_value=[{"source": "Schwab"}]):
            self.assertEqual(load_chain.__wrapped__(date(2027, 1, 15), "call")[0]["source"], "Schwab")

    def test_quote_failure_propagates_without_fallback(self):
        from live_market_quote import fetch_live_quote
        with patch.object(provider, "fetch_quote", side_effect=provider.SchwabError("Schwab needs authorization")):
            with self.assertRaises(provider.SchwabError):
                fetch_live_quote.__wrapped__()

    def test_benchmark_uses_schwab_and_preserves_actual_price(self):
        from benchmark_quotes import fetch_quote
        now = provider.datetime.now(provider.timezone.utc).isoformat()
        with patch.object(provider, "fetch_quote", return_value={
            "price": 49.5, "observed_at": now, "stale": False, "source": "Schwab"}):
            quote = fetch_quote("TQQQ")
        self.assertEqual(quote["price"], 49.5)
        self.assertEqual(quote["source"], "Schwab")

    def test_diagnostics_reports_authorization_missing_not_healthy(self):
        from full_diagnostics import _schwab
        with patch.object(provider, "fetch_quote") as fetch:
            state, message = _schwab()
        self.assertEqual(state, "warning")
        self.assertIn("authorize", message)
        fetch.assert_not_called()


class OAuthTests(AsyncHTTPTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "SCHWAB_CLIENT_ID": "test-client", "SCHWAB_CLIENT_SECRET": "test-secret",
            "SCHWAB_REDIRECT_URI": "https://soxl.ai/auth/schwab/callback"}, clear=True)
        self.env.start()
        self.store = MemoryStore()
        self.store_patches = [
            patch.object(provider.token_store, "locked", self.store.locked),
            patch.object(provider.token_store, "read", self.store.read)]
        for item in self.store_patches:
            item.start()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        for item in self.store_patches:
            item.stop()
        self.env.stop()

    def get_app(self):
        return Application([(r"/auth/schwab/connect", auth.Connect),
                            (r"/auth/schwab/callback", auth.Callback),
                            (r"/api/schwab/status", auth.Status)])

    def begin(self):
        response = self.fetch("/auth/schwab/connect", headers={"Host": "soxl.ai"},
                              follow_redirects=False)
        self.assertEqual(response.code, 302)
        text = response.body.decode()
        self.assertNotIn("test-secret", text)
        self.assertNotIn("<form", text)
        params = parse_qs(urlsplit(response.headers["Location"]).query)
        cookie = SimpleCookie()
        cookie.load(response.headers["Set-Cookie"])
        self.assertTrue(cookie[auth.COOKIE]["secure"])
        self.assertTrue(cookie[auth.COOKIE]["httponly"])
        self.assertEqual(cookie[auth.COOKIE]["samesite"], "Lax")
        self.assertEqual(cookie[auth.COOKIE]["path"], "/auth/schwab")
        return params["state"][0], cookie.output(header="").strip().split(";")[0]

    def authorize(self):
        return self.fetch("/auth/schwab/connect", headers={
            "Host": "soxl.ai", "X-Forwarded-Proto": "https"}, follow_redirects=False)

    def test_unauthorized_visitor_cannot_replace_owner_connection(self):
        with patch.object(provider, "exchange_code") as exchange:
            response = self.fetch("/auth/schwab/callback?code=untrusted&state=wrong")
            self.assertEqual(response.code, 403)
            exchange.assert_not_called()
        _, cookie = self.begin()
        response = self.fetch("/auth/schwab/connect", method="POST", headers={
            "Host": "soxl.ai", "Cookie": cookie},
            body="secret=wrong")
        self.assertEqual(response.code, 405)

    def test_oauth_redirect_and_callback(self):
        response = self.authorize()
        self.assertEqual(response.code, 302)
        url = urlsplit(response.headers["Location"])
        self.assertEqual(url.netloc, "api.schwabapi.com")
        params = parse_qs(url.query)
        self.assertEqual(params["client_id"], ["test-client"])
        self.assertEqual(params["response_type"], ["code"])
        self.assertEqual(params["redirect_uri"], ["https://soxl.ai/auth/schwab/callback"])
        self.assertNotIn("test-secret", response.headers["Location"])
        cookie = SimpleCookie()
        cookie.load(response.headers["Set-Cookie"])
        with patch.object(provider, "exchange_code") as exchange:
            response = self.fetch("/auth/schwab/callback?" + urlencode({
                "state": params["state"][0], "code": "test-code"}),
                headers={"Host": "soxl.ai", "Cookie": cookie.output(header="").strip().split(";")[0]},
                follow_redirects=False)
            self.assertEqual(response.code, 302)
            self.assertEqual(response.headers["Location"], "/")
            exchange.assert_called_once_with("test-code")

    def test_preview_domain_does_not_start_broken_cross_domain_oauth(self):
        response = self.fetch("/auth/schwab/connect", follow_redirects=False)
        self.assertNotIn("Set-Cookie", response.headers)
        self.assertEqual(response.code, 302)
        self.assertEqual(response.headers["Location"], "https://soxl.ai/auth/schwab/connect")

    def test_direct_redirect_does_not_require_entering_secret(self):
        with patch.dict(os.environ, {"SCHWAB_CLIENT_SECRET": " \ttest-secret\r\n"}):
            response = self.authorize()
            self.assertEqual(response.code, 302)
            self.assertTrue(response.headers["Location"].startswith(
                "https://api.schwabapi.com/v1/oauth/authorize?"))
            self.assertNotIn("test-secret", response.headers["Location"])

    def test_state_mismatch_never_exchanges_code(self):
        _, cookie = self.begin()
        with patch.object(provider, "exchange_code") as exchange, self.assertLogs(level="WARNING") as logs:
            response = self.fetch("/auth/schwab/callback?code=private-code&state=wrong",
                                  headers={"Host": "soxl.ai", "Cookie": cookie})
        self.assertEqual(response.code, 403)
        exchange.assert_not_called()
        self.assertIn("reason=oauth_state_invalid", "\n".join(logs.output))
        self.assertNotIn("private-code", "\n".join(logs.output))

    def test_callback_stores_tokens_before_redirect_home(self):
        state, cookie = self.begin()
        with patch.object(provider, "_token_request", return_value={
                    "access_token": "private-access", "refresh_token": "private-refresh",
                    "expires_at": time.time() + 1800}) as token_request:
            response = self.fetch("/auth/schwab/callback?" + urlencode({
                "state": state, "code": "private-code"}),
                headers={"Host": "soxl.ai", "Cookie": cookie, "X-Forwarded-Proto": "https"},
                follow_redirects=False)
            self.assertEqual(response.code, 302)
            self.assertEqual(response.headers["Location"], "/")
            self.assertEqual(provider.status()["state"], "authorized")
            self.assertEqual(provider._read()["refresh_token"], "private-refresh")
            self.assertGreater(provider._read()["refresh_expires_at"], time.time() + 6 * 86400)
            token_request.assert_called_once_with({
                "grant_type": "authorization_code", "code": "private-code",
                "redirect_uri": "https://soxl.ai/auth/schwab/callback"})
            for secret in ("private-code", "private-access", "private-refresh", "test-secret"):
                self.assertNotIn(secret, response.body.decode() + str(response.headers))

    def test_cancelled_authorization_does_not_redirect_home(self):
        state, cookie = self.begin()
        with patch.object(provider, "exchange_code") as exchange:
            response = self.fetch("/auth/schwab/callback?" + urlencode({
                "state": state, "error": "access_denied"}),
                headers={"Host": "soxl.ai", "Cookie": cookie}, follow_redirects=False)
        self.assertEqual(response.code, 400)
        exchange.assert_not_called()

    def test_exchange_failure_does_not_redirect_home(self):
        state, cookie = self.begin()
        with patch.object(provider, "exchange_code", side_effect=provider.SchwabError("Schwab rejected authorization.")):
            response = self.fetch("/auth/schwab/callback?" + urlencode({
                "state": state, "code": "private-code"}),
                headers={"Host": "soxl.ai", "Cookie": cookie}, follow_redirects=False)
        self.assertEqual(response.code, 502)
        self.assertNotIn("Location", response.headers)


if __name__ == "__main__":
    unittest.main()
