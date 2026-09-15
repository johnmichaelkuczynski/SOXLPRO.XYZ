import unittest
from threading import Event
import time
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from area_lab import jobs


SCRIPT = r"""
import sys
import types

import numpy as np
import pandas as pd
import streamlit as st


feature_module = types.ModuleType("area_lab.features")


def build_features(ohlc, config):
    frame = pd.DataFrame(index=ohlc.index)
    frame["close"] = ohlc["Close"]
    frame["anchor_date"] = ohlc.index
    frame["anchor_price"] = ohlc["Close"].shift(1)
    frame["anchor_type"] = "low20"
    frame["anchor_confirmation_date"] = ohlc.index
    frame["elapsed_sessions"] = 1.0
    frame["area_raw"] = 1.0
    frame["area_log"] = 0.1
    frame["area_signed"] = 0.1
    frame["area_norm"] = 0.2
    return frame


feature_module.build_features = build_features
feature_module.add_targets = lambda features, horizons: features
sys.modules["area_lab.features"] = feature_module

model_module = types.ModuleType("area_lab.models")


def run_lab(features, config, progress=None, cancel_event=None):
    return {
        "comparison": pd.DataFrame(),
        "regression": pd.DataFrame(),
        "buckets": pd.DataFrame(),
        "predictions": pd.DataFrame(),
        "calibration": pd.DataFrame(),
        "coefficients": pd.DataFrame(),
        "confusion": pd.DataFrame(),
        "splits": pd.DataFrame(),
        "warnings": [],
        "verdict": "No evidence",
        "verdict_detail": "Fast mocked worker for the AppTest.",
        "config": config,
    }


model_module.run_lab = run_lab
sys.modules["area_lab.models"] = model_module

from area_lab.ui import render_area_lab

dates = pd.bdate_range("2018-01-02", periods=140)
close = 10 + np.arange(len(dates)) * 0.03
data = pd.DataFrame(
    {
        "Open": close - 0.1,
        "High": close + 0.2,
        "Low": close - 0.2,
        "Close": close,
    },
    index=dates,
)
render_area_lab(data)
"""


class AreaLabUITests(unittest.TestCase):
    def test_panel_is_lazy_until_enabled(self):
        app = AppTest.from_string(SCRIPT).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.checkbox(key="area_lab_enabled").value, False)
        self.assertEqual(len(app.button), 0)

    def test_controls_and_fast_mocked_analysis_render_without_live_api(self):
        app = AppTest.from_string(SCRIPT).run(timeout=30)
        app.checkbox(key="area_lab_enabled").check().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(
            any(button.label == "Analyze Historical Predictiveness" for button in app.button)
        )
        app.button(key="area_lab_analyze").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertTrue(any("No evidence" in info.value for info in app.info))
        self.assertGreaterEqual(len(app.get("download_button")), 9)
        self.assertTrue(
            any("mathematical persistence" in warning.value for warning in app.warning)
        )
        # The finished registry entry is released after capture, while
        # session_state keeps the complete result/downloads across reruns.
        app.run(timeout=30)
        self.assertFalse(app.exception)
        self.assertGreaterEqual(len(app.get("download_button")), 9)


class AreaLabJobTests(unittest.TestCase):
    @staticmethod
    def _ohlc(marker: float) -> pd.DataFrame:
        index = pd.bdate_range("2020-01-02", periods=8)
        # Keep the fixture deliberately small; the worker functions are mocked.
        values = marker + pd.Series(range(len(index)), index=index, dtype=float)
        return pd.DataFrame(
            {
                "Open": values,
                "High": values + 1,
                "Low": values - 1,
                "Close": values,
            },
            index=index,
        )

    def test_distinct_sessions_cannot_reuse_or_mix_results(self):
        started = Event()

        def fake_features(ohlc, config):
            started.set()
            return pd.DataFrame({"marker": [float(ohlc["Close"].iloc[0])]}, index=[ohlc.index[0]])

        def fake_targets(features, horizons):
            return features

        def fake_lab(features, config, progress=None, cancel_event=None):
            if progress:
                progress(1.0, "done")
            return {"marker": float(features["marker"].iloc[0])}

        with patch("area_lab.features.build_features", fake_features), patch(
            "area_lab.features.add_targets", fake_targets
        ), patch("area_lab.models.run_lab", fake_lab):
            first = jobs.start_analysis_job(self._ohlc(10), {"horizons": [1]}, "session-a")
            second = jobs.start_analysis_job(self._ohlc(20), {"horizons": [1]}, "session-b")
            self.assertNotEqual(first, second)
            self.assertTrue(started.wait(2))
            one = jobs.wait_for_job(first, timeout=2)
            two = jobs.wait_for_job(second, timeout=2)
        self.assertEqual(one["status"], "completed")
        self.assertEqual(two["status"], "completed")
        self.assertEqual(one["result"]["marker"], 10.0)
        self.assertEqual(two["result"]["marker"], 20.0)

    def test_running_interrupted_error_is_a_cancellation(self):
        entered = Event()

        def fake_features(ohlc, config):
            return pd.DataFrame({"marker": [1.0]}, index=[ohlc.index[0]])

        def fake_lab(features, config, progress=None, cancel_event=None):
            entered.set()
            while not cancel_event.is_set():
                time.sleep(0.005)
            raise InterruptedError("cancelled")

        with patch("area_lab.features.build_features", fake_features), patch(
            "area_lab.features.add_targets", lambda features, horizons: features
        ), patch("area_lab.models.run_lab", fake_lab):
            job_id = jobs.start_analysis_job(
                self._ohlc(1), {"horizons": [1]}, "cancel-running"
            )
            self.assertTrue(entered.wait(2))
            self.assertTrue(jobs.cancel_job(job_id))
            result = jobs.wait_for_job(job_id, timeout=2)
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(result["result"])

    def test_queued_job_can_be_cancelled_without_a_result(self):
        entered = []
        entered_lock = Event()
        release = Event()

        def fake_features(ohlc, config):
            return pd.DataFrame({"marker": [1.0]}, index=[ohlc.index[0]])

        def fake_lab(features, config, progress=None, cancel_event=None):
            entered.append(True)
            entered_lock.set()
            while not release.is_set():
                if cancel_event.is_set():
                    raise InterruptedError("cancelled")
                time.sleep(0.005)
            return {"ok": True}

        with patch("area_lab.features.build_features", fake_features), patch(
            "area_lab.features.add_targets", lambda features, horizons: features
        ), patch("area_lab.models.run_lab", fake_lab):
            first = jobs.start_analysis_job(self._ohlc(1), {"horizons": [2]}, "queue-a")
            second = jobs.start_analysis_job(self._ohlc(2), {"horizons": [2]}, "queue-b")
            # The bounded executor has two active slots.
            deadline = time.monotonic() + 2
            while len(entered) < 2 and time.monotonic() < deadline:
                entered_lock.wait(0.02)
                entered_lock.clear()
            self.assertEqual(len(entered), 2)
            queued = jobs.start_analysis_job(self._ohlc(3), {"horizons": [2]}, "queue-c")
            self.assertTrue(jobs.cancel_job(queued))
            queued_result = jobs.wait_for_job(queued, timeout=2)
            release.set()
            jobs.cancel_job(first)
            jobs.cancel_job(second)
            jobs.wait_for_job(first, timeout=2)
            jobs.wait_for_job(second, timeout=2)
        self.assertEqual(queued_result["status"], "cancelled")
        self.assertIsNone(queued_result["result"])


if __name__ == "__main__":
    unittest.main()
