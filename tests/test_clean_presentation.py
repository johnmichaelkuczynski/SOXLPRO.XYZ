from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile

from backtest_engine import build_report_docx, build_report_pdf, build_report_text
from clean_presentation import CLEAN_NOTICE_STYLE, apply_clean_presentation
from seo import ABOUT_HTML
from strategy_builder import render_strategy_html


def test_operational_messages_use_neutral_panels_without_hiding_their_text():
    assert '[data-testid="stAlert"]' in CLEAN_NOTICE_STYLE
    assert "background: transparent !important" in CLEAN_NOTICE_STYLE
    assert "color: #334155 !important" in CLEAN_NOTICE_STYLE
    assert "svg { display: none" in CLEAN_NOTICE_STYLE
    with patch("streamlit.html") as render:
        apply_clean_presentation()
    render.assert_called_once_with(CLEAN_NOTICE_STYLE)


def test_about_copy_has_no_financial_disclaimer():
    for phrase in ("not investment advice", "not guaranteed", "may be delayed",
                   "past performance", "understand the risks"):
        assert phrase not in ABOUT_HTML.lower()


def test_saved_strategy_disclaimer_is_not_rendered():
    rendered = render_strategy_html({
        "title": "Test strategy", "disclaimer": "legacy-warning",
    })
    assert "legacy-warning" not in rendered
    assert 'class="disclaimer"' not in rendered


def test_text_report_keeps_results_without_a_disclaimer():
    report = build_report_text(
        "Test", {"Observed price": 50.25}, "Measured returns", [],
    )
    assert "50.25" in report
    assert "RESULTS" in report
    assert "disclaimer" not in report.lower()
    assert "past performance" not in report.lower()


def test_docx_report_keeps_results_without_a_disclaimer():
    report = build_report_docx(
        "Test", {"Observed price": 50.25}, "Measured returns", [],
    )
    with ZipFile(BytesIO(report)) as archive:
        document = archive.read("word/document.xml").decode("utf-8")
    assert "50.25" in document
    assert "disclaimer" not in document.lower()
    assert "past performance" not in document.lower()


def test_pdf_report_has_no_disclaimer_paragraph():
    from reportlab.platypus import Paragraph

    with patch("reportlab.platypus.Paragraph", wraps=Paragraph) as paragraph:
        report = build_report_pdf(
            "Test", {"Observed price": 50.25}, "Measured returns", [],
        )
    assert report.startswith(b"%PDF")
    text = " ".join(str(call.args[0]) for call in paragraph.call_args_list).lower()
    assert "disclaimer" not in text
    assert "past performance" not in text
