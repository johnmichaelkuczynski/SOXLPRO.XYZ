"""No real credentials, account consent, provider calls, or token files."""
from datetime import date
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlencode, urlsplit

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

import schwab_market_data as provider
import schwab_auth as auth


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "SCHWAB_CLIENT_ID": "test-client", "SCHWAB_CLIENT_SECRET": "test-secret",
            "SCHWAB_TOKEN_FILE": self.temp.name + "/tokens.json"}, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def save(self, **overrides):
        value = dict(app=provider._fingerprint(), access_token="test-access",
                     refresh_token="test-refresh", expires_at=time.time() + 1800,
                     authorized_at="2026-11-15T00:00:00+00:00")
        value.update(overrides)
        with provider._locked():
            provider._write(value)

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

    def test_valid_token_reused_and_file_private(self):
        self.save()
        self.assertEqual(stat.S_IMODE(provider.token_path().stat().st_mode), 0o600)
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
        with patch.object(provider.requests, "post", return_value=response):
            with self.assertRaises(provider.SchwabError):
                provider.access_token()
        self.assertEqual(provider.status()["state"], "authorization_required")

    def test_quote_timestamp_is_trade_time_not_quote_time(self):
        now = int(time.time() * 1000)
        data = {"SOXL": {"realtime": False, "quote": {
            "lastPrice": 50.25, "tradeTime": now - 120000, "quoteTime": now}}}
        quote = provider.parse_quote(data, "SOXL")
        self.assertEqual(quote["price"], 50.25)
        self.assertTrue(quote["delayed"])
        self.assertIn("delayed", quote["source"])
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

    def test_quote_integration_prefers_schwab_and_falls_back_explicitly(self):
        from live_market_quote import fetch_live_quote
        quote = dict(price=50, stale=False, source="Schwab")
        with patch.object(provider, "fetch_quote", return_value=quote), patch(
                "live_market_quote.yf.Ticker") as yahoo:
            self.assertEqual(fetch_live_quote.__wrapped__(), quote)
            yahoo.assert_not_called()

    def test_options_integration_uses_schwab_first(self):
        from options_projection_data import load_chain
        with patch.object(provider, "load_option_chain", return_value=[{"source": "Schwab"}]):
            self.assertEqual(load_chain.__wrapped__(date(2027, 1, 15), "call")[0]["source"], "Schwab")

    def test_quote_fallback_reports_missing_authorization(self):
        from live_market_quote import fetch_live_quote
        yahoo = Mock()
        yahoo.info = dict(regularMarketPrice=51, regularMarketTime=time.time())
        with patch.object(provider, "fetch_quote", side_effect=provider.SchwabError("Schwab needs authorization")), \
                patch("live_market_quote.yf.Ticker", return_value=yahoo), \
                patch("live_market_quote.requests.get", side_effect=RuntimeError):
            quote = fetch_live_quote.__wrapped__()
        self.assertEqual(quote["source"], "Yahoo Finance")
        self.assertIn("Schwab needs authorization", quote["feed_warning"])

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
        auth.ATTEMPTS.clear()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.env.stop()

    def get_app(self):
        return Application([(r"/auth/schwab/connect", auth.Connect),
                            (r"/auth/schwab/callback", auth.Callback),
                            (r"/api/schwab/status", auth.Status)])

    def begin(self):
        response = self.fetch("/auth/schwab/connect", headers={"Host": "soxl.ai"})
        self.assertEqual(response.code, 200)
        text = response.body.decode()
        self.assertNotIn("test-secret", text)
        nonce = re.search(r'name="nonce" value="([^"]+)"', text)[1]
        cookie = SimpleCookie()
        cookie.load(response.headers["Set-Cookie"])
        self.assertTrue(cookie[auth.COOKIE]["secure"])
        self.assertTrue(cookie[auth.COOKIE]["httponly"])
        return nonce, cookie.output(header="").strip().split(";")[0]

    def authorize(self):
        nonce, cookie = self.begin()
        response = self.fetch("/auth/schwab/connect", method="POST", headers={
            "Host": "soxl.ai", "Cookie": cookie,
            "Content-Type": "application/x-www-form-urlencoded"},
            body=urlencode(dict(nonce=nonce, secret="test-secret")), follow_redirects=False)
        return response

    def test_unauthorized_visitor_cannot_replace_owner_connection(self):
        with patch.object(provider, "exchange_code") as exchange:
            response = self.fetch("/auth/schwab/callback?code=untrusted&state=wrong")
            self.assertEqual(response.code, 403)
            exchange.assert_not_called()
        nonce, cookie = self.begin()
        response = self.fetch("/auth/schwab/connect", method="POST", headers={
            "Host": "soxl.ai", "Cookie": cookie},
            body=urlencode(dict(nonce=nonce, secret="wrong")))
        self.assertEqual(response.code, 403)

    def test_oauth_redirect_and_callback(self):
        response = self.authorize()
        self.assertEqual(response.code, 302)
        url = urlsplit(response.headers["Location"])
        self.assertEqual(url.netloc, "api.schwabapi.com")
        params = parse_qs(url.query)
        self.assertEqual(params["redirect_uri"], ["https://soxl.ai/auth/schwab/callback"])
        self.assertNotIn("test-secret", response.headers["Location"])
        cookie = SimpleCookie()
        cookie.load(response.headers["Set-Cookie"])
        with patch.object(provider, "exchange_code") as exchange:
            response = self.fetch("/auth/schwab/callback?" + urlencode({
                "state": params["state"][0], "code": "test-code"}),
                headers={"Host": "soxl.ai", "Cookie": cookie.output(header="").strip().split(";")[0]})
            self.assertEqual(response.code, 200)
            self.assertIn(b"authorization saved", response.body)
            exchange.assert_called_once_with("test-code")

    def test_preview_domain_does_not_start_broken_cross_domain_oauth(self):
        response = self.fetch("/auth/schwab/connect")
        self.assertNotIn("Set-Cookie", response.headers)
        self.assertIn(b"configured domain", response.body)

    def test_post_without_csrf_cookie_is_rejected(self):
        response = self.fetch("/auth/schwab/connect", method="POST",
                              body="secret=test-secret&nonce=untrusted")
        self.assertEqual(response.code, 403)


if __name__ == "__main__":
    unittest.main()
