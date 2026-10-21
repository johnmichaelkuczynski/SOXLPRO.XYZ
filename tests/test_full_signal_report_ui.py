from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest


class FullSignalReportUITests(unittest.TestCase):
    def test_view_shows_exact_download_and_hide_preserves_download(self):
        app = AppTest.from_string("""
import pandas as pd
from short_term_signal_ui import render_short_term_signal, render_full_signal_report
render_short_term_signal(pd.Series([90., 95.], index=pd.to_datetime(['2026-10-19','2026-10-20'])))
render_full_signal_report()
""", default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.get("iframe")), 0)
        self.assertEqual(len(app.get("download_button")), 1)
        app.button(key="view_full_signal_report").click().run()
        self.assertFalse(app.exception)
        frame = app.get("iframe")[0].proto
        self.assertEqual(frame.srcdoc, Path("reports/signal_validation/report.html").read_text())
        self.assertTrue(frame.scrolling)
        self.assertEqual(len(app.get("download_button")), 1)
        app.run()
        self.assertEqual(len(app.get("iframe")), 1)
        app.button(key="view_full_signal_report").click().run()
        self.assertEqual(len(app.get("iframe")), 0)
        self.assertEqual(len(app.get("download_button")), 1)


if __name__ == "__main__":
    unittest.main()
