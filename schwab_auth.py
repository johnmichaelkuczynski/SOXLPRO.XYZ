"""Direct Schwab OAuth connection; this never gates public app access."""
import asyncio
import hashlib
import hmac
import html
import logging
import secrets
from urllib.parse import urlencode, urlsplit

import tornado.web

import schwab_market_data as schwab

COOKIE = "soxl_schwab_setup"


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
            self.redirect(f"https://{callback.netloc}/auth/schwab/connect")
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
            self.setup_failure("oauth_state_invalid",
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
        # Ensure the homepage's independently refreshed price uses the newly
        # authorized connection rather than a previously cached account quote.
        from live_market_quote import fetch_live_quote
        fetch_live_quote.clear()
        self.redirect("/")


class Status(Base):
    def get(self):
        self.finish(schwab.status())
