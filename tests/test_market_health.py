"""Offline evidence checks for diagnostics and independent worker heartbeats."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import market_health as health
import market_state_store as store
from test_market_state import payload


NOW = datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc)
STAMP = NOW.isoformat()


class HealthTests(unittest.TestCase):
    def evidence(self, status="ok", stamp=STAMP):
        return {"status": status, "checked_at": STAMP,
                "worker_read_status": "ok" if status in ("ok", "empty") else status,
                "worker": {"heartbeat_at": stamp, "phase": "partial_failure"}}

    def lines(self, saved=None, evidence=None):
        return "\n".join(health.diagnostic_lines(saved, evidence or self.evidence(), NOW))

    def test_missing_database_read_never_implies_running_worker(self):
        for status in ("failed", "timeout", "busy", "not_checked"):
            text = self.lines(payload(), self.evidence(status))
            self.assertIn("Unknown; database read did not verify worker health", text)
            self.assertIn("Retained saved results", text)
            self.assertNotIn("Recent heartbeat verified", text)

    def test_heartbeat_is_independent_of_usable_saved_results(self):
        text = self.lines(None, self.evidence("empty"))
        self.assertIn("Recent heartbeat verified", text)
        self.assertIn("no saved results found", text)
        self.assertIn("Results: Unavailable", text)

    def test_old_missing_and_invalid_heartbeats(self):
        self.assertIn("Heartbeat overdue", self.lines(evidence=self.evidence(
            stamp="2026-01-05T17:00:00+00:00")))
        for stamp in (None, "bad", "2026-01-05T18:00:00", "2099-01-05T18:00:00+00:00"):
            self.assertIn("Unknown; no valid heartbeat", self.lines(
                evidence=self.evidence(stamp=stamp)))

    def test_failed_component_keeps_original_success_and_quote_observation(self):
        saved = payload()
        saved["quote"] = {"price": 22, "observed_at": STAMP}
        saved["status"] = {"components": {"quote": {
            "last_success_at": "2026-01-05T17:55:00+00:00",
            "last_attempt_at": STAMP, "stale": True}}}
        text = self.lines(saved)
        self.assertIn("Latest update failed", text)
        self.assertIn("Last success: 2026-01-05T17:55:00+00:00", text)
        self.assertIn("Retained observation; not verified current", text)
        saved["status"]["components"]["quote"]["stale"] = False
        self.assertIn("Current timestamped observation", self.lines(saved))
        saved["quote"]["observed_at"] = "2026-01-05T17:00:00+00:00"
        self.assertIn("Retained observation", self.lines(saved))

    def test_database_evidence_available_even_without_saved_state(self):
        with patch.object(store, "_execute", side_effect=[None, (self.evidence()["worker"],)]):
            with patch.object(store, "_last_good", None):
                self.assertIsNone(store.load_state())
                evidence = store.read_health(refresh=True)
        self.assertEqual(evidence["status"], "empty")
        self.assertEqual(evidence["worker"]["heartbeat_at"], STAMP)
        evidence["worker"]["phase"] = "mutated"
        self.assertNotEqual(store.read_health()["worker"]["phase"], "mutated")

    def test_missing_optional_health_table_cannot_hide_existing_saved_results(self):
        def execute(sql, **kwargs):
            if "market_worker_health" in sql:
                raise store.StateStoreError("UndefinedTable")
            return (payload(),)
        with patch.object(store, "_execute", side_effect=execute), \
                patch.object(store, "_last_good", None):
            saved = store.load_state()
            evidence = store.read_health(refresh=True)
        self.assertEqual(saved["history"], payload()["history"])
        self.assertEqual(evidence["status"], "ok")
        self.assertEqual(evidence["worker_read_status"], "failed")
        self.assertIn("did not verify worker health", self.lines(saved, evidence))

    def test_new_background_snapshot_does_not_relabel_open_chart(self):
        displayed = payload()
        displayed["quote"] = {"price": 21, "observed_at": STAMP}
        latest = payload()
        latest["computed_at"] = "2026-01-05T18:01:00+00:00"
        latest["quote"] = {"price": 25, "observed_at": latest["computed_at"]}
        latest["status"] = {"components": {"quote": {
            "last_success_at": latest["computed_at"], "stale": False}}}
        text = "\n".join(health.diagnostic_lines(displayed, self.evidence(), NOW, latest=latest))
        self.assertIn("Displayed analysis snapshot: " + displayed["computed_at"], text)
        self.assertIn("newer background results are available", text)
        self.assertIn("chart has not been reset", text)
        self.assertNotIn("Current timestamped observation", text)
        self.assertIn("Last success: " + latest["computed_at"], text)

    def test_slow_health_probe_does_not_block_primary_results(self):
        import threading
        gate = threading.Event()
        def execute(sql, **kwargs):
            if "market_worker_health" in sql:
                gate.wait(1)
                return None
            return (payload(),)
        try:
            with patch.object(store, "_execute", side_effect=execute), \
                    patch.object(store, "READ_BUDGET_SECONDS", 0.01):
                evidence = store.read_health(refresh=True)
                self.assertEqual(evidence["worker_read_status"], "timeout")
                self.assertEqual(store.load_state()["history"], payload()["history"])
                gate.set()
                # Wait for the independent reader to release its slot.
                with store._health_slot:
                    pass
        finally:
            gate.set()

    def test_heartbeat_write_contains_no_market_payload(self):
        with patch.object(store, "_execute") as execute:
            store.save_worker_health("updating")
        sql, params = execute.call_args.args
        self.assertIn("market_worker_health", sql)
        self.assertIn("heartbeat_at", params[0])
        self.assertNotIn("history", params[0])

    def test_optional_schema_failure_does_not_prevent_market_schema_setup(self):
        with patch.object(store, "_execute", side_effect=[
                None, store.StateStoreError("InsufficientPrivilege")]) as execute:
            store.ensure_schema()
        self.assertIn("CREATE TABLE IF NOT EXISTS market_state", execute.call_args_list[0].args[0])
        self.assertEqual(execute.call_count, 2)

    def test_failed_heartbeat_writes_do_not_stop_successful_market_updates(self):
        from contextlib import contextmanager
        from unittest.mock import MagicMock
        import market_state_worker as worker
        @contextmanager
        def lock():
            yield MagicMock()
        updated = payload()
        updated["status"] = {"stale": False}
        with patch.object(worker, "worker_lock", lock), \
                patch.object(worker, "ensure_schema"), \
                patch.object(worker, "load_state", return_value=payload()), \
                patch.object(worker, "recompute", return_value=updated), \
                patch.object(worker, "save_worker_health",
                             side_effect=store.StateStoreError("UndefinedTable")) as heartbeat, \
                patch.object(worker, "save_state") as save:
            self.assertEqual(worker.run(once=True), 0)
        save.assert_called_once_with(updated)
        self.assertEqual(heartbeat.call_count, 2)

    def test_gateway_no_state_does_not_claim_worker_running(self):
        from fast_gateway import saved_page
        with patch.object(store, "read_health", return_value={"status": "failed"}):
            page = saved_page(None)
        self.assertNotIn("Background refresh is running", page)
        self.assertIn("database read did not verify worker health", page)

    def test_render_escapes_untrusted_content(self):
        saved = payload()
        saved["quote"] = {"observed_at": "<script>bad()</script>"}
        self.assertNotIn("<script>", health.diagnostics_html(saved, self.evidence()))


if __name__ == "__main__":
    unittest.main()
