import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest


class ChannelReportUITests(unittest.TestCase):
    def test_report_is_visible_and_download_is_preserved(self):
        app = AppTest.from_string(
            "from area_lab.channel_report_ui import render_channel_validation\n"
            "render_channel_validation()", default_timeout=30
        ).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.get("download_button")), 6)
        self.assertEqual(len(app.dataframe), 1)
        self.assertIn("No demonstrated area advantage", app.info[0].value)
        app.checkbox(key="channel_report_visible").check().run()
        self.assertEqual(len(app.exception), 0)
        report = Path("reports/channel_validation/report.html").read_text()
        self.assertEqual(app.get("iframe")[0].proto.srcdoc, report)
        self.assertEqual(len(app.get("download_button")), 6)


if __name__ == "__main__":
    unittest.main()
