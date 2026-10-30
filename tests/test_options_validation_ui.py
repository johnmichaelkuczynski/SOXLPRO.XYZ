import io
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from test_options_validation import inputs


SCRIPT = "from options_validation_ui import render_validation\nrender_validation()"


def test_empty_ui_has_no_implicit_study():
    with patch("options_validation_ui.run_study") as run:
        app = AppTest.from_string(SCRIPT).run()
        assert not app.exception
        assert app.button(key="options_study_run").disabled
        assert len(app.get("download_button")) == 1
        assert "No study" in app.info[0].value
        run.assert_not_called()


def test_uploaded_study_download_and_changed_input_invalidation():
    h, q, s = inputs()
    uploads = dict(zip(
        ["options_study_history", "options_study_quotes", "options_study_sessions"],
        [io.BytesIO(df.to_csv(index=False).encode()) for df in
         [h, q, pd.DataFrame({"timestamp": s})]],
    ))
    with patch("options_validation_ui.st.file_uploader",
               side_effect=lambda *args, **kwargs: uploads[kwargs["key"]]):
        app = AppTest.from_string(SCRIPT, default_timeout=30).run()
        assert not app.exception
        app.button(key="options_study_run").click().run()
        assert not app.exception
        assert len(app.metric) == 3
        assert len(app.get("download_button")) == 2
        assert "remain unvalidated" in app.info[0].value
        app.number_input(key="options_study_fee").set_value(1.).run()
        assert not app.exception
        assert len(app.metric) == 0
        assert len(app.get("download_button")) == 1


def test_invalid_upload_shows_error_not_results():
    with patch("options_validation_ui.st.file_uploader",
               return_value=io.BytesIO(b"bad\n1\n")):
        app = AppTest.from_string(SCRIPT).run()
        app.button(key="options_study_run").click().run()
        assert not app.exception
        assert len(app.error) == 1
        assert not app.metric
