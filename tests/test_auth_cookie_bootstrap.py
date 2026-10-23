"""Exercise the real Streamlit WebSocket auth gate, without Google credentials."""
import json
from http.cookies import SimpleCookie
from unittest.mock import Mock

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application
from streamlit.web.server.browser_websocket_handler import BrowserWebSocketHandler
from streamlit_backend import PublicDocumentHandler


class CookieBootstrapTests(AsyncHTTPTestCase):
    def get_app(self):
        return Application([
            (r"/", PublicDocumentHandler, {
                "body": "<html>app</html>", "content_type": "text/html",
                "production": True,
            }),
        ], xsrf_cookies=True, xsrf_cookie_name="_streamlit_xsrf",
            cookie_secret="test-only-secret")

    def test_page_sets_token_that_passes_streamlit_auth_validation(self):
        response = self.fetch("/")
        cookies = SimpleCookie()
        for value in response.headers.get_list("Set-Cookie"):
            cookies.load(value)
        self.assertIn("_streamlit_xsrf", cookies)
        token = cookies["_streamlit_xsrf"].value
        self.assertFalse(cookies["_streamlit_xsrf"]["httponly"])
        request = Mock()
        request.headers = {"Origin": "https://app.example"}
        request.cookies = SimpleCookie(f"_streamlit_xsrf={token}")
        handler = BrowserWebSocketHandler(self._app, request, runtime=Mock())
        self.assertTrue(handler._validate_xsrf_token(token))
        self.assertFalse(handler._validate_xsrf_token("invalid"))
        identity = handler._parse_user_cookie(json.dumps({
            "origin": "https://app.example", "is_logged_in": True,
            "sub": "test-user",
        }).encode())
        self.assertTrue(identity["is_logged_in"])
        self.assertEqual(identity["sub"], "test-user")

    def test_return_visit_preserves_existing_token(self):
        first = self.fetch("/")
        cookies = SimpleCookie(first.headers["Set-Cookie"])
        token = cookies["_streamlit_xsrf"].value
        second = self.fetch("/", headers={"Cookie": f"_streamlit_xsrf={token}"})
        self.assertEqual(second.code, 200)
        self.assertNotIn("Set-Cookie", second.headers)
