from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd

from short_term_signal_ui import render_short_term_signal


def test_technical_details_and_warnings_stay_in_closed_dropdown():
    active = []
    writes = []

    @contextmanager
    def dropdown(name, **kwargs):
        assert name == "Frozen short-term rule and validation"
        assert kwargs == {"expanded": False}
        active.append(name)
        yield
        active.pop()

    def record(text):
        writes.append((text, bool(active)))

    saved = {
        "short_rating": "NO EDGE",
        "manifest": {
            "passed": False,
            "rule_text": "Frozen rule",
            "test_metrics": {
                "observations": 4, "finished_higher_pct": 75,
                "baseline_pct": 56.2, "difference_pp": 18.8,
                "median_return_pct": 33.5, "average_worst_dip_pct": -14.1,
            },
        },
    }
    closes = pd.Series([50.0], index=pd.to_datetime(["2026-11-13"]))
    with patch("short_term_signal_ui.st") as ui, patch(
        "short_term_signal_ui.REPORT_PATH"
    ) as report:
        report.exists.return_value = False
        ui.expander.side_effect = dropdown
        ui.write.side_effect = record
        ui.warning.side_effect = record
        render_short_term_signal(closes, saved=saved)
        visible = ui.markdown.call_args.args[0]
        assert "NO CALL" in visible
        assert "Not enough history to predict the next month either way." in visible
        for technical in ("Frozen rule", "Median return", "Too thin", "Close through"):
            assert technical not in visible
            assert any(technical in text and inside for text, inside in writes)
        assert all(inside for _, inside in writes)
