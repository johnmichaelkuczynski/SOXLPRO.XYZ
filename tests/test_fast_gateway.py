import unittest
from unittest.mock import patch
from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application, RequestHandler
from tornado.httpserver import HTTPServer
from tornado.netutil import bind_sockets
import fast_gateway


class Upstream(RequestHandler):
    def get(self, path):
        if self.request.headers.get("If-None-Match") == '"fixture"':
            self.set_status(304)
            self.finish()
            return
        self.set_header("Content-Type", "application/javascript")
        self.set_header("ETag", '"fixture"')
        self.add_header("Set-Cookie", "one=1; HttpOnly")
        self.add_header("Set-Cookie", "two=2; HttpOnly")
        self.finish("console.log('ready')")


class GatewayTests(AsyncHTTPTestCase):
    def get_app(self):
        sockets = bind_sockets(0, "127.0.0.1")
        self.backend = HTTPServer(Application([(r"/(.*)", Upstream)]))
        self.backend.add_sockets(sockets)
        self.target = patch.object(fast_gateway, "BACKEND",
                                   f"http://127.0.0.1:{sockets[0].getsockname()[1]}")
        self.target.start()
        fast_gateway.ready = True
        return Application([(r"/(.*)", fast_gateway.Gateway)])

    def tearDown(self):
        self.backend.stop()
        self.target.stop()
        super().tearDown()

    def test_javascript_mime_and_cookies(self):
        result = self.fetch("/static/app.js")
        self.assertEqual(result.code, 200)
        self.assertEqual(result.headers.get_list("Content-Type"), ["application/javascript"])
        self.assertEqual(len(result.headers.get_list("Set-Cookie")), 2)

    def test_conditional_reload_is_not_503(self):
        result = self.fetch("/", headers={"If-None-Match": '"fixture"'})
        self.assertEqual(result.code, 304)
        self.assertEqual(result.body, b"")

    def test_ready_health_preserves_backend_cookies(self):
        result = self.fetch("/_stcore/health")
        self.assertEqual(result.code, 200)
        self.assertEqual(len(result.headers.get_list("Set-Cookie")), 2)

    def test_boot_health_remains_fast(self):
        fast_gateway.ready = False
        result = self.fetch("/_stcore/health")
        self.assertEqual(result.code, 200)
        self.assertEqual(result.body, b"ok")

    def test_reconnecting_tab_waits_for_backend(self):
        fast_gateway.ready = False
        self.io_loop.call_later(0.2, lambda: setattr(fast_gateway, "ready", True))
        result = self.fetch("/_stcore/host-config")
        self.assertEqual(result.code, 200)
        self.assertIn(b"ready", result.body)

    def test_cached_fallback_rechecks_database_and_labels_retained_results(self):
        from datetime import datetime, timezone
        import market_state_store as store
        from test_market_state import payload
        saved = payload()
        saved["quote"] = {"price": 21, "observed_at": datetime.now(timezone.utc).isoformat()}
        with patch.object(fast_gateway, "ready", False), \
                patch.object(fast_gateway, "state", None), \
                patch.object(store, "_last_good", None), \
                patch.object(store, "_execute", side_effect=[
                    (saved,), None,
                    store.StateStoreError("OperationalError"),
                    store.StateStoreError("OperationalError"),
                ]) as execute:
            first = self.fetch("/")
            second = self.fetch("/")
        self.assertIn(b"Current timestamped observation", first.body)
        self.assertIn(b"Retained saved results", second.body)
        self.assertIn(b"Database read: Failed", second.body)
        self.assertNotIn(b"Current timestamped observation", second.body)
        self.assertEqual(execute.call_count, 4)

    def test_cached_fallback_displays_newly_read_snapshot(self):
        import market_state_store as store
        from test_market_state import payload
        old, new = payload(), payload()
        new["computed_at"] = "2026-01-06T18:00:00+00:00"
        with patch.object(fast_gateway, "ready", False), \
                patch.object(fast_gateway, "state", old), \
                patch.object(store, "_execute", side_effect=[(new,), None]):
            page = self.fetch("/").body.decode()
        self.assertIn("Saved results computed at " + new["computed_at"], page)
        self.assertIn("Displayed analysis snapshot: " + new["computed_at"], page)


if __name__ == "__main__":
    unittest.main()
