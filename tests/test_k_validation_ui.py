import json
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from scripts.k_validation_report import fingerprint


def test_released_evidence_matches_frozen_inputs():
    root = Path("reports/k_validation")
    frozen = json.loads((root/"protocol.json").read_text())
    # A later live-model revision must not invalidate already released evidence.
    # The evaluator itself refuses reruns against any changed code or data.
    current = fingerprint()
    source = "docs/soxl_signal_study_prices.csv"
    assert frozen["hashes"][source] == current[source]
    assert all(len(digest) == 64 for digest in frozen["hashes"].values())
    assert json.loads((root/"conclusion.json").read_text())["status"] == "Unvalidated"
    records = pd.read_csv(root/"outcomes.csv")
    assert (records.loc[records.partition == "training", "end_date"] <= "2018-12-31").all()
    assert (records.loc[records.partition == "holdout", "date"] >= "2019-01-01").all()
    assert (records.entry_date > records.date).all()


def test_report_and_horizon_selection():
    app = AppTest.from_string(
        "from k_validation_ui import render_k_validation\nrender_k_validation()",
        default_timeout=30,
    ).run()
    assert not app.exception
    assert len(app.dataframe) == 2
    assert len(app.get("download_button")) == 1
    assert "unvalidated" in app.warning[0].value
    assert "nan" not in app.warning[0].value
    assert app.dataframe[0].value.horizon.eq(21).all()
    app.selectbox(key="k_evidence_horizon").select(63).run()
    assert not app.exception
    assert app.dataframe[0].value.horizon.eq(63).all()
