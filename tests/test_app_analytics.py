import json
import unittest
from pathlib import Path
from unittest.mock import patch

import app_analytics


class _Session(dict):
    pass


class AppAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.session = _Session()
        self.session_patch = patch.object(app_analytics.st, "session_state", self.session)
        self.session_patch.start()
        self.addCleanup(self.session_patch.stop)
        self.preview_patch = patch.object(
            app_analytics, "is_development_preview", return_value=False
        )
        self.preview_patch.start()
        self.addCleanup(self.preview_patch.stop)

    def test_server_allowlist_and_property_enums(self):
        self.assertTrue(
            app_analytics.track_event(
                "checkout_ready", {"location": "buy_dialog"}
            )
        )
        self.assertFalse(
            app_analytics.track_event(
                "checkout_ready",
                {"location": "buy_dialog", "prompt": "private"},
            )
        )
        self.assertFalse(
            app_analytics.track_event(
                "payment_confirmed", {"plan": "pro"}
            )
        )
        self.assertFalse(
            app_analytics.track_event(
                "not_an_event", {"url": "https://private.example/?q=secret"}
            )
        )
        self.assertEqual(len(self.session[app_analytics.QUEUE_KEY]), 1)
        self.assertNotIn("prompt", json.dumps(self.session))

    def test_once_key_is_hashed_and_deduplicated(self):
        self.assertTrue(
            app_analytics.track_event(
                "strategy_requested",
                {"feature": "strategy_builder"},
                once_key="raw-private-key",
            )
        )
        self.assertFalse(
            app_analytics.track_event(
                "strategy_requested",
                {"feature": "strategy_builder"},
                once_key="raw-private-key",
            )
        )
        queued = self.session[app_analytics.QUEUE_KEY]
        self.assertEqual(len(queued), 1)
        self.assertNotIn("raw-private-key", json.dumps(self.session))
        self.assertNotIn("once_key", queued[0])

    def test_preview_skips_queue_and_mount(self):
        with patch.object(app_analytics, "is_development_preview", return_value=True), \
                patch.object(app_analytics.st.components.v1, "html") as mount:
            self.assertFalse(
                app_analytics.track_event(
                    "signed_in_session", {"tier": "signed_in"}
                )
            )
            self.assertFalse(app_analytics.flush_analytics())
            mount.assert_not_called()
        self.assertNotIn(app_analytics.QUEUE_KEY, self.session)

    def test_checkout_and_confirmation_do_not_share_dedup_namespace(self):
        self.assertTrue(app_analytics.track_event(
            "checkout_ready", {"location": "buy_dialog"}, once_key="same-checkout"))
        self.assertTrue(app_analytics.track_event(
            "payment_confirmed", {"plan": "full_access"}, once_key="same-checkout"))
        queued = self.session[app_analytics.QUEUE_KEY]
        self.assertEqual(len(queued), 2)
        self.assertNotEqual(queued[0]["id"], queued[1]["id"])
        self.assertNotIn("same-checkout", json.dumps(queued))

    def test_mount_failure_preserves_queue_and_success_clears_it(self):
        app_analytics.track_event(
            "market_question_submitted", {"feature": "market_chat"}
        )
        with patch.object(
            app_analytics.st.components.v1,
            "html",
            side_effect=RuntimeError("tracker unavailable"),
        ):
            self.assertFalse(app_analytics.flush_analytics())
        self.assertEqual(len(self.session[app_analytics.QUEUE_KEY]), 1)

        with patch.object(app_analytics.st.components.v1, "html") as mount:
            self.assertTrue(app_analytics.flush_analytics())
            mount.assert_called_once()
            self.assertEqual(mount.call_args.kwargs["height"], 0)
            self.assertEqual(self.session[app_analytics.QUEUE_KEY], [])

    def test_payload_escapes_script_terminator_characters(self):
        # Invalid properties cannot be queued, so test the encoder directly
        # with a representative hostile value.
        document = app_analytics._document(
            Path(app_analytics.BRIDGE_PATH).read_text(),
            [{"id": "x", "name": "market_question_submitted",
              "properties": {"feature": "market_chat"}}],
        )
        self.assertEqual(document.lower().count("</script>"), 2)
        encoded = app_analytics._script_json({"text": "</script><script>unsafe"})
        self.assertNotIn("</script>", encoded.lower())
        self.assertIn("__APP_ANALYTICS_PENDING__", document)


if __name__ == "__main__":
    unittest.main()