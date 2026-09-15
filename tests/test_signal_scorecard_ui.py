import unittest

from streamlit.testing.v1 import AppTest


SCRIPT = """
import streamlit as st
import pandas as pd
import numpy as np
from signal_scorecard_ui import render_rating_scorecard
dates = pd.bdate_range("2015-01-01", periods=900)
closes = pd.Series(50 + 20*np.sin(np.arange(900)/31) + np.arange(900)/20, index=dates)
render_rating_scorecard(closes, "POSSIBLE BUY")
"""


class ScorecardUITests(unittest.TestCase):
    def test_scorecard_opens_and_survives_horizon_rating_and_sampling_changes(self):
        app = AppTest.from_string(SCRIPT).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.selectbox), 0)
        app.button(key="daily_rating_scorecard_run").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.selectbox(key="daily_rating_category").value, "POSSIBLE BUY")
        self.assertTrue(any("Reconstructed" in c.value for c in app.caption))
        app.selectbox(key="daily_rating_horizon").select("3 months (63 trading days)").run(timeout=30)
        app.selectbox(key="daily_rating_category").select("BUY").run(timeout=30)
        app.checkbox(key="daily_rating_spaced").check().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertTrue(any("63 trading days after entry" in c.value for c in app.caption))
        self.assertGreaterEqual(len(app.dataframe), 2)
        self.assertEqual(len(app.get("download_button")), 2)

    def test_short_history_does_not_claim_success(self):
        app = AppTest.from_string(SCRIPT.replace("periods=900", "periods=3").replace(
            "np.arange(900)", "np.arange(3)"
        )).run(timeout=30)
        app.button(key="daily_rating_scorecard_run").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertTrue(any("No completed" in x.value or "not enough" in x.value for x in app.info))


if __name__ == "__main__":
    unittest.main()