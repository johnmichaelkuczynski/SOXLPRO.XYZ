from streamlit.testing.v1 import AppTest


def test_slider_timeframe_and_reset(monkeypatch):
    # AppTest cannot operate iframe widgets. Exercise the Python bridge here;
    # the component's live input behavior is checked in a real browser.
    import price_probability_slider
    selection = {"value": None}
    def slider(prepared, value, horizon, label, token=0):
        return value if token or selection["value"] is None else selection["value"]
    monkeypatch.setattr(price_probability_slider, "probability_slider", slider)
    app = AppTest.from_string("""
import numpy as np
import pandas as pd
from price_scenario_ui import render_price_scenario
rng = np.random.default_rng(43)
closes = pd.Series(40*np.exp(np.cumsum(rng.normal(0,.025,4000))),
                   index=pd.bdate_range('2010-01-01',periods=4000))
render_price_scenario(closes, 40.55, 'Saved test quote')
""").run(timeout=20)
    assert not app.exception
    assert app.session_state["price_scenario_selected_price"] == 40.55
    app.selectbox[0].select("One month").run()
    selection["value"] = 35.0
    app.run()
    assert not app.exception
    assert app.session_state["price_scenario_selected_price"] == 35.0
    assert len(app.metric) == 2
    selection["value"] = 500.0
    app.run()
    assert not app.exception
    assert len(app.metric) == 0
    assert any("outside" in item.value for item in app.warning)
    app.button[0].click().run()
    assert app.session_state["price_scenario_selected_price"] == 40.55
    assert not app.exception
