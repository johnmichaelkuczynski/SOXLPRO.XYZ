import json
from unittest.mock import patch
from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

import full_diagnostics as diagnostics


def test_failures_never_expose_exception_messages():
    def fail():
        raise RuntimeError("PRIVATE_KEY_SHOULD_NEVER_APPEAR")
    row = diagnostics._run_check("Probe", "Test", fail)
    assert row["status"] == "fail"
    assert "PRIVATE_KEY" not in json.dumps(row)


def test_runner_missing_is_not_a_pass():
    with patch.object(diagnostics.subprocess, "run", side_effect=OSError):
        rows = diagnostics._regressions()
    assert rows[0]["status"] == "not_tested"


def test_single_flight_does_not_launch_duplicate_jobs():
    with patch.object(diagnostics, "_jobs", {}), patch.object(diagnostics, "_active", None), \
            patch.object(diagnostics.threading, "Thread") as thread:
        first = diagnostics.start_job("http://127.0.0.1:5000")
        second = diagnostics.start_job("http://127.0.0.1:5000")
    assert first == second
    assert thread.call_count == 1


def test_retained_snapshot_never_claims_fresh_database_read():
    fallback = {"history": {"prices": [1] * 300, "dates": ["2026-11-04"] * 300},
                "signal": {"composite": {"signal": "BUY"}, "close_date": "2026-11-04"}}
    with patch.object(diagnostics, "_database_snapshot", side_effect=RuntimeError), \
            patch("market_state_store._read_disk_snapshot", return_value=fallback):
        rows = diagnostics._saved_checks()
    assert rows[0]["name"] == "Fresh database read" and rows[0]["status"] == "fail"
    assert rows[1]["status"] == "pass" and "NOT a successful database read" in rows[1]["detail"]
    assert len([row for row in rows if row["group"] == "Benchmarks" and row["status"] == "fail"]) == 8


class DiagnosticsHTTPTests(AsyncHTTPTestCase):
    def get_app(self):
        return Application([
            (r"/api/diagnostics/run", diagnostics.DiagnosticsRun, {"port": 5000}),
            (r"/api/diagnostics/([a-f0-9]{32})", diagnostics.DiagnosticsStatus),
        ])

    def test_one_post_starts_job_without_waiting(self):
        with patch.object(diagnostics, "start_job", return_value="a" * 32):
            response = self.fetch("/api/diagnostics/run", method="POST", body="{}",
                                  headers={"Content-Type": "application/json"})
        assert response.code == 200
        assert json.loads(response.body)["id"] == "a" * 32

    def test_cross_origin_job_is_rejected(self):
        with patch.object(diagnostics, "start_job") as start:
            response = self.fetch("/api/diagnostics/run", method="POST", body="{}",
                                  headers={"Content-Type": "application/json", "Origin": "https://other.example"})
        assert response.code == 403
        start.assert_not_called()

    def test_plain_form_cannot_trigger_paid_probes(self):
        with patch.object(diagnostics, "start_job") as start:
            response = self.fetch("/api/diagnostics/run", method="POST", body="")
        assert response.code == 415
        start.assert_not_called()

    def test_internal_metadata_is_not_returned(self):
        with patch.object(diagnostics, "_jobs", {"a" * 32: {"running": False, "checks": [], "_started": 123}}):
            response = self.fetch("/api/diagnostics/" + "a" * 32)
        assert response.code == 200
        assert "_started" not in json.loads(response.body)

    def test_expired_run_has_explicit_failure(self):
        with patch.object(diagnostics, "_jobs", {}):
            response = self.fetch("/api/diagnostics/" + "b" * 32)
        assert response.code == 404
