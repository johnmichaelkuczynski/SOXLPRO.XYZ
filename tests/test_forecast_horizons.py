from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from forecast_horizons import earliest_historical_outlook


def series(values):
    return pd.Series(values, index=pd.bdate_range("2019-01-02", periods=len(values)))


def test_shortest_horizon_is_chosen_without_optimizing_the_outcome_rate():
    result = earliest_historical_outlook(series(np.arange(400.) + 1))
    assert result["selected"]["sessions"] == 1
    assert result["selected"]["observations"] >= 30
    assert result["selected"]["higher_pct"] == 100
    assert result["rating"] == "SELL"
    assert "BUY" not in result


def test_entry_is_next_session_close_not_the_signal_close():
    closes = series(np.where(np.arange(400) % 2, 100., 50.))
    row = earliest_historical_outlook(closes)["selected"]
    assert row["sessions"] == 1
    # SELL observations fall on $100 days. Entry is the following $50 close,
    # then exit at $100; using the signal close would incorrectly report losses.
    assert row["observations"] == 199
    assert row["wins"] == 199


def test_common_schedule_is_selected_before_filtering_by_current_rating():
    closes = series(np.arange(401.) + 1)
    percentiles = np.where(np.arange(401) % 2, 100., 10.)
    percentiles[0] = np.nan
    frame = pd.DataFrame({"percentile": percentiles}, index=closes.index)
    with patch("forecast_horizons.features", return_value=frame):
        result = earliest_historical_outlook(closes)
    assert result["rating"] == "BUY"
    assert result["candidates"][0]["observations"] == 0
    assert result["selected"]["sessions"] == 2
    assert result["selected"]["observations"] >= 30


def test_incomplete_and_post_cutoff_outcomes_are_excluded():
    closes = series(np.arange(400.) + 1)
    end = closes.index[249].date().isoformat()
    before = earliest_historical_outlook(closes.iloc[:250], end=end)
    after = earliest_historical_outlook(closes, end=end)
    assert before["selected"] == after["selected"]
    assert before["candidates"] == after["candidates"]


@pytest.mark.parametrize("closes", [
    pd.Series(dtype=float), series([10., 11.]), series(np.full(400, 10.)),
])
def test_missing_history_never_fabricates_a_horizon_or_frequency(closes):
    result = earliest_historical_outlook(closes)
    assert result["selected"] is None


def test_minimum_cannot_silently_weaken_the_existing_sample_floor():
    with pytest.raises(ValueError, match="30"):
        earliest_historical_outlook(series(np.arange(400.) + 1), min_observations=2)


def test_frequency_interval_and_baseline_are_inspectable():
    selected = earliest_historical_outlook(series(np.arange(400.) + 1))["selected"]
    assert 0 <= selected["interval_low_pct"] <= selected["higher_pct"]
    assert selected["higher_pct"] <= selected["interval_high_pct"] <= 100
    assert selected["baseline_pct"] == 100
    assert selected["difference_pp"] == 0


def test_card_shows_horizon_and_historical_frequency_not_the_old_dead_end():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string("""
import numpy as np
import pandas as pd
from short_term_signal_ui import render_short_term_signal
closes = pd.Series(np.arange(400.) + 1,
                   index=pd.bdate_range("2019-01-02", periods=400))
render_short_term_signal(closes)
""", default_timeout=30).run()
    assert not app.exception
    visible_card = app.markdown[0].value
    assert "EARLIEST HISTORICAL OUTLOOK" in visible_card
    assert "1 TRADING DAY" in visible_card
    assert "100% finished higher" in visible_card
    assert "NO CALL" not in visible_card
    assert "Not enough history to predict" not in visible_card
    assert app.expander[0].label == "Outlook evidence and frozen monthly rule"
