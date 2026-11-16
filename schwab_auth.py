"""Owner-only OAuth setup; this never gates public access to the SOXL app."""
import asyncio
import hashlib
import hmac
import html
import logging
import secrets
import time
from collections import OrderedDict
from urllib.parse import urlencode, urlsplit

import tornado.web

import schwab_market_data as schwab

COOKIE = "soxl_schwab_setup"
ATTEMPTS = OrderedDict()


def _cookie_secret():
    # Dedicated purpose, derived server-side. Never sent to the browser.
    return hmac.new(schwab.client_secret().encode(),
                    b"soxl-schwab-owner-oauth", hashlib.sha256).digest()


class Base(tornado.web.RequestHandler):
    def setup_failure(self, reason, message, status=403):
        # Fixed reason codes and booleans only: never log POST bodies, cookies,
        # nonces, secret values, secret lengths, or credential fingerprints.
        forwarded = self.request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip().lower()
        logging.warning(
            "Schwab setup rejected reason=%s cookie_present=%s "
            "backend_https=%s forwarded_https=%s",
            reason, bool(self.get_cookie(COOKIE)),
            self.request.protocol == "https", forwarded == "https")
        self.set_status(status)
        self.page("Setup was not authorized", message)

    def set_default_headers(self):
        self.set_header("Cache-Control", "no-store")
        self.set_header("Referrer-Policy", "no-referrer")
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("Content-Security-Policy",
                        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")

    def _request_summary(self):
        # Authorization codes are single-use secrets, not access-log content.
        return f"{self.request.method} {self.request.path} ({self.request.remote_ip})"

    def log_exception(self, typ, value, tb):
        logging.error("Schwab setup failed (%s)", typ.__name__)

    def page(self, title, message, extra=""):
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.finish("<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'>"
                    "<title>Schwab market-data setup</title><style>"
                    "body{max-width:650px;margin:10vh auto;padding:24px;font:17px system-ui;color:#172033}"
                    "input,button{display:block;padding:12px;margin:16px 0;width:100%;box-sizing:border-box}"
                    "button{background:#1565c0;color:white;border:0;border-radius:6px}</style>"
                    f"<h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>{extra}")

    def set_setup(self, data):
        value = tornado.web.create_signed_value(_cookie_secret(), COOKIE, data).decode()
        self.set_cookie(COOKIE, value, secure=True, httponly=True, samesite="Lax",
                        path="/auth/schwab", max_age=600)

    def get_setup(self):
        if not self.get_cookie(COOKIE):
            return None
        value = tornado.web.decode_signed_value(
            _cookie_secret(), COOKIE, self.get_cookie(COOKIE, ""), max_age_days=10 / 1440)
        return value.decode() if value else None

    def clear_setup(self):
        self.clear_cookie(COOKIE, path="/auth/schwab")


class Connect(Base):
    def get(self):
        if not schwab.configured():
            self.set_status(503)
            self.page("Schwab keys are not configured",
                      "Set SCHWAB_CLIENT_ID and SCHWAB_CLIENT_SECRET on this server. The main app remains available.")
            return
        callback = urlsplit(schwab.redirect_uri())
        if callback.scheme != "https" or callback.path != "/auth/schwab/callback" or callback.query or callback.fragment:
            self.set_status(503)
            self.page("Check the Schwab callback URL", "Configure a valid HTTPS SCHWAB_REDIRECT_URI.")
            return
        # Set up and complete OAuth on the same host; do not issue a cookie
        # on a preview domain that can never accompany the production callback.
        if self.request.host != callback.netloc:
            self.page("Open setup on your configured domain",
                      "Schwab must return to the same domain that starts authorization.",
                      '<a href="' + html.escape(f"https://{callback.netloc}/auth/schwab/connect", quote=True)
                      + '">Open Schwab setup on the configured domain</a>')
            return
        nonce = secrets.token_urlsafe(32)
        self.set_setup("form:" + nonce)
        self.page("Connect Schwab market data",
                  schwab.status()["message"] + " This owner-only setup does not sign visitors in or enable trading.",
                  '<form method="post" action="/auth/schwab/connect">'
                  '<input type="hidden" name="nonce" value="' + nonce + '">'
                  '<label for="secret">Schwab app secret — owner verification</label>'
                  '<input id="secret" name="secret" type="password" required autocomplete="off">'
                  '<button>Authorize with Schwab</button></form>'
                  '<p>Use your existing Schwab app secret to protect this shared market-data connection. '
                  'Then sign in on Schwab’s own website. Schwab normally requires reconnection about weekly.</p>')

    def post(self):
        now = time.monotonic()
        for key in (self.request.remote_ip, "*"):
            history = [stamp for stamp in ATTEMPTS.get(key, []) if now - stamp < 60]
            ATTEMPTS[key] = history
            if len(history) >= (5 if key != "*" else 60):
                self.setup_failure("rate_limited", "Too many setup attempts. Retry in one minute.", 429)
                return
            history.append(now)
        while len(ATTEMPTS) > 1000:
            ATTEMPTS.popitem(last=False)
        if not schwab.configured():
            self.setup_failure("configuration_missing",
                               "Schwab keys are not configured on this server.", 503)
            return
        callback = urlsplit(schwab.redirect_uri())
        if self.request.host != callback.netloc:
            self.setup_failure("wrong_host", "Open setup on the registered callback domain.")
            return
        if not self.get_cookie(COOKIE):
            self.setup_failure("cookie_missing",
                               "The setup cookie did not return. Open this page directly on the callback domain "
                               "over HTTPS with cookies enabled, then submit again.")
            return
        expected = self.get_setup()
        if not expected:
            self.setup_failure("cookie_invalid_or_expired",
                               "The setup cookie expired or could not be verified. Reopen this page and retry. "
                               "All server instances must use the same Schwab app secret.")
            return
        nonce = self.get_body_argument("nonce", "", strip=False)
        if not nonce or not hmac.compare_digest(expected.encode(), ("form:" + nonce).encode()):
            self.setup_failure("nonce_mismatch", "The form no longer matches this browser's setup cookie. "
                               "Reopen this page and submit the newest form.")
            return
        secret = self.get_body_argument("secret", "", strip=False).strip()
        if not hmac.compare_digest(secret.encode(), schwab.client_secret().encode()):
            self.setup_failure("secret_mismatch",
                               "The entered app secret does not match this server's SCHWAB_CLIENT_SECRET. "
                               "Check the running container's configuration and retry.")
            return
        state = secrets.token_urlsafe(32)
        self.set_setup("oauth:" + state)
        self.redirect("https://api.schwabapi.com/v1/oauth/authorize?" + urlencode({
            "response_type": "code", "client_id": schwab.client_id(),
            "redirect_uri": schwab.redirect_uri(), "state": state}))


class Callback(Base):
    async def get(self):
        state = self.get_query_argument("state", "")
        expected = self.get_setup()
        self.clear_setup()
        if not expected or not state or not hmac.compare_digest(expected.encode(), ("oauth:" + state).encode()):
            self.set_status(403)
            self.page("Authorization could not be verified",
                      "Start again at /auth/schwab/connect in this browser. No connection was changed.")
            return
        code = self.get_query_argument("code", "")
        if self.get_query_argument("error", "") or not code:
            self.set_status(400)
            self.page("Schwab authorization was not completed", "No connection was changed. You can try setup again.")
            return
        try:
            await asyncio.to_thread(schwab.exchange_code, code)
        except schwab.SchwabError as exc:
            self.set_status(502)
            self.page("Schwab could not connect", str(exc))
            return
        except OSError:
            self.set_status(503)
            self.page("Schwab authorization could not be saved",
                      "Configure a private writable SCHWAB_TOKEN_FILE location, then reconnect.")
            return
        self.page("Schwab authorization saved",
                  "The app can now request Schwab market data. Background prices update on their normal schedule. "
                  "No trades or account changes were made.", '<a href="/">Return to SOXL</a>')


class Status(Base):
    def get(self):
        self.finish(schwab.status())
