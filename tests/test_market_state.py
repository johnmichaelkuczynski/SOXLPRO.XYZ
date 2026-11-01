"""Focused persistence/worker tests. No network or database needed."""
import copy
import importlib
import json
import logging
import math
import subprocess
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

import market_state_store as store
import market_state_worker as worker


def payload():
    return {
        "version": 1, "computed_at": "2026-01-05T18:00:00+00:00",
        "history": {"dates": ["2026-01-02", "2026-01-05"], "prices": [20.0, 21.0]},
        "quote": None, "market_feed": {"points": [], "error": "unavailable"},
        "snapshot": {"current_price": 21.0, "returns": {"Year": float("nan")}},
        "signal": {
            "readings": [], "composite": {"percentile": 50, "signal": "DO NOTHING"},
            "close_date": "2026-01-05", "short_rating": "NO EDGE", "manifest": {},
        },
        "overlays": {},
    }


class StoreTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        store._last_good = None
        self.snapshot_dir = tempfile.TemporaryDirectory()
        self.snapshot_path = Path(self.snapshot_dir.name) / "last-market-state.json"
        self.snapshot_patch = patch.object(store, "_DISK_SNAPSHOT", self.snapshot_path)
        self.snapshot_patch.start()
        self.addCleanup(self.snapshot_patch.stop)
        self.addCleanup(self.snapshot_dir.cleanup)

    def connection(self, state=None):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = (state,) if state else None
        return conn, cur

    def test_lightweight_import_does_not_import_ui_or_market_libraries(self):
        script = (
            "import sys; import market_state_store; "
            "assert not ({'streamlit','pandas','numpy','yfinance','app'} & set(sys.modules))"
        )
        subprocess.run([sys.executable, "-c", script], check=True, capture_output=True)

    def test_read_is_select_only_has_short_sql_timeout_and_closes(self):
        conn, cur = self.connection(payload())
        with patch.object(store, "get_conn", return_value=conn):
            actual = store.load_state()
        self.assertEqual(actual["version"], 1)
        statements = [call.args[0] for call in cur.execute.call_args_list]
        self.assertTrue(any("statement_timeout" in sql for sql in statements))
        self.assertFalse(any("CREATE" in sql or "INSERT" in sql for sql in statements))
        conn.close.assert_called_once()

    def test_save_atomic_upsert_and_no_nonfinite_json(self):
        conn, cur = self.connection()
        with patch.object(store, "get_conn", return_value=conn):
            store.save_state(payload())
        sql, params = cur.execute.call_args.args
        self.assertIn("ON CONFLICT", sql)
        self.assertNotIn("NaN", params[0])
        self.assertIsNone(json.loads(params[0])["snapshot"]["returns"]["Year"])
        conn.close.assert_called_once()

    def test_database_outage_uses_validated_last_snapshot_and_close(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            disk = Path(directory) / "last-market-state.json"
            with patch.object(store, "_DISK_SNAPSHOT", disk):
                store._last_good = None
                store._save_disk_snapshot(payload())
                with patch.object(store, "_execute", side_effect=store.StateStoreError("Unavailable")):
                    retained = store.load_state()
            self.assertEqual(retained["history"]["prices"][-1], 21.0)
            self.assertIn("showing saved results", retained["_read_warning"])

    def test_bundled_snapshot_is_valid_and_has_last_known_price(self):
        bundled = store._read_disk_snapshot()
        self.assertIsNotNone(bundled)
        self.assertTrue(store._valid_state(bundled))
        self.assertGreater(bundled["snapshot"]["current_price"], 0)
        self.assertEqual(len(bundled["history"]["dates"]), len(bundled["history"]["prices"]))

    def test_invalid_or_missing_disk_snapshot_never_fabricates_price(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            disk = Path(directory) / "last-market-state.json"
            bundled = Path(directory) / "missing-bundle.json"
            with patch.object(store, "_DISK_SNAPSHOT", disk), \
                    patch.object(store, "_BUNDLED_SNAPSHOT", bundled):
                store._last_good = None
                disk.write_text('{"version":99}')
                self.assertIsNone(store._retained_state("Database unavailable"))

    def test_bad_state_cannot_replace_last_good(self):
        for bad in (
            {**payload(), "version": 2},
            {**payload(), "version": True},
            {**payload(), "computed_at": "2026-01-05T18:00:00"},
            {**payload(), "history": {"dates": ["2026-01-05"], "prices": [math.nan]}},
            {**payload(), "history": {"dates": [], "prices": []}},
        ):
            with self.subTest(bad=bad), patch.object(store, "get_conn") as connect:
                with self.assertRaises(ValueError):
                    store.save_state(bad)
                connect.assert_not_called()

    def test_error_messages_never_contain_driver_secrets(self):
        secret = "postgres://identity:secret@private.example/path?api_key=secret"
        with patch.object(store, "get_conn", side_effect=RuntimeError(secret)):
            with self.assertLogs(store.LOG, logging.WARNING) as logs:
                self.assertIsNone(store.load_state())
            self.assertNotIn(secret, "".join(logs.output))
            with self.assertRaises(store.StateStoreError) as error:
                store.save_state(payload())
            self.assertEqual(str(error.exception), "RuntimeError")

    def test_connection_budget_singleflight_and_eventual_disposal(self):
        conn, _ = self.connection(payload())

        def delayed():
            time.sleep(0.08)
            return conn

        with patch.object(store, "get_conn", side_effect=delayed) as connect:
            with patch.object(store, "READ_BUDGET_SECONDS", 0.01):
                start = time.monotonic()
                self.assertIsNone(store.load_state())
                self.assertIsNone(store.load_state())
                self.assertLess(time.monotonic() - start, 0.06)
            time.sleep(0.12)
        connect.assert_called_once()
        conn.close.assert_called_once()

    def test_refresh_hint_does_no_work(self):
        with patch.object(store, "get_conn") as connect:
            self.assertFalse(store.request_refresh())
            connect.assert_not_called()

    def test_outage_retains_results_and_marks_them(self):
        with patch.object(store, "_execute", return_value=(payload(),)):
            self.assertIsNotNone(store.load_state())
        with patch.object(store, "_execute", side_effect=store.StateStoreError("OperationalError")):
            retained = store.load_state()
        self.assertEqual(retained["history"], payload()["history"])
        self.assertIn("_read_warning", retained)
        retained["history"]["prices"][0] = 999
        self.assertEqual(store._last_good["history"]["prices"][0], 20)

    def test_busy_read_keeps_last_good(self):
        store._last_good = payload()
        with store._read_slot:
            result = store.load_state()
        self.assertEqual(result["computed_at"], payload()["computed_at"])
        self.assertIn("_read_warning", result)

    def test_late_success_is_kept_for_next_request(self):
        def delayed(*args, **kwargs):
            time.sleep(0.05)
            return (payload(),)
        with patch.object(store, "_execute", side_effect=delayed), \
                patch.object(store, "READ_BUDGET_SECONDS", 0.005):
            self.assertIsNone(store.load_state())
            time.sleep(0.09)
            with store._read_slot:
                self.assertEqual(store.load_state()["history"], payload()["history"])


class WorkerTests(unittest.TestCase):
    def test_completed_closes_and_no_edge_preserved(self):
        from landing_signal import completed_close_history
        frame = pd.DataFrame(
            {"Close": [20.0, 21.0, 1000.0]},
            index=pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
        )
        now = datetime.fromisoformat("2026-01-06T12:00:00-05:00")
        completed = completed_close_history(frame, now=now)
        history = worker._pack_history(completed.to_frame("Close"))
        result = worker.compute_signal(history)
        self.assertEqual(result["close_date"], "2026-01-05")
        self.assertEqual(result["short_rating"], "NO EDGE")
        self.assertIsInstance(result["readings"], list)
        json.dumps(result, allow_nan=False)

    def test_failed_feeds_keep_last_good_and_mark_stale(self):
        previous = payload()
        previous["quote"] = {
            "price": 21.5, "observed_at": "2026-01-05T18:00:00+00:00", "source": "Yahoo Finance",
        }
        previous["market_feed"] = {"points": [{"price": 21.5}], "checked": "old"}
        before = copy.deepcopy(previous)
        with patch.object(worker, "refresh_quote", return_value=None), \
             patch.object(worker, "refresh_feed", return_value={"points": [], "error": "failed"}), \
             patch.object(worker, "refresh_snapshot", side_effect=ValueError("secret URL")):
            updated = worker.recompute(previous, refresh_history=False)
        self.assertEqual(previous, before)
        self.assertEqual(updated["quote"]["price"], 21.5)
        self.assertTrue(updated["quote"]["stale"])
        self.assertEqual(updated["market_feed"]["points"], before["market_feed"]["points"])
        self.assertEqual(updated["snapshot"]["current_price"], 21.0)
        self.assertTrue(updated["status"]["stale"])
        self.assertNotIn("secret URL", json.dumps(updated))
        self.assertEqual(updated["signal"]["short_rating"], "NO EDGE")

    def test_history_failure_retains_history_signal_and_allows_quote(self):
        previous = payload()
        quote = {"price": 22, "observed_at": datetime.now(timezone.utc).isoformat()}
        with patch.object(worker, "download_history", side_effect=RuntimeError("private")), \
             patch.object(worker, "OVERLAY_SYMBOLS", {}), \
             patch.object(worker, "refresh_quote", return_value=quote), \
             patch.object(worker, "refresh_feed", return_value={"points": [{"price": 22}]}), \
             patch.object(worker, "refresh_snapshot", return_value={"current_price": 22}):
            updated = worker.recompute(previous)
        self.assertEqual(updated["history"], previous["history"])
        self.assertEqual(updated["signal"], previous["signal"])
        self.assertEqual(updated["quote"]["price"], 22)
        self.assertTrue(updated["status"]["components"]["history"]["stale"])

    def test_no_initial_history_is_not_usable(self):
        with patch.object(worker, "download_history", side_effect=RuntimeError("secret")):
            self.assertIsNone(worker.recompute())

    def test_refresh_provider_not_request_reader(self):
        import chart_market_feed
        with patch.object(chart_market_feed, "refresh_chart_market_feed", return_value={"points": [1]}, create=True) as provider, \
             patch.object(chart_market_feed, "fetch_chart_market_feed", side_effect=AssertionError("request reader called")):
            self.assertEqual(worker.refresh_feed(), {"points": [1]})
        provider.assert_called_once()

    def test_singleton_lock_and_connection_disposal(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = (False,)
        with patch.object(worker, "get_conn", return_value=conn):
            with worker.worker_lock() as owned:
                self.assertIsNone(owned)
        self.assertTrue(any("pg_try_advisory_lock" in call.args[0] for call in cur.execute.call_args_list))
        conn.close.assert_called_once()

    def test_provider_deadline(self):
        with self.assertRaises(TimeoutError):
            with worker.deadline(0.01):
                time.sleep(0.1)

    def test_once_returns_failure_without_usable_state_and_success_with_last_good(self):
        from contextlib import contextmanager

        @contextmanager
        def lock():
            yield MagicMock()

        for previous, expected in ((None, 1), (payload(), 0)):
            with self.subTest(expected=expected), \
                 patch.object(worker, "worker_lock", lock), \
                 patch.object(worker, "ensure_schema"), \
                 patch.object(worker, "load_state", return_value=previous), \
                 patch.object(worker, "recompute", return_value=None), \
                 patch.object(worker, "save_worker_health") as heartbeat, \
                 patch.object(worker, "save_state") as save:
                self.assertEqual(worker.run(once=True), expected)
                save.assert_not_called()
                self.assertEqual([c.args[0] for c in heartbeat.call_args_list],
                                 ["updating", "update_failed"])


if __name__ == "__main__":
    unittest.main()
