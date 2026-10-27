import numpy as np
import pandas as pd
import pytest
from continuous_price_model import prepare_history, estimate, probability_curve, fit_model


def history():
    rng = np.random.default_rng(80)
    log = [4.]
    for _ in range(4200):
        log.append(log[-1] + .025*(4-log[-1]) + rng.normal(0,.08))
    return pd.Series(np.exp(log), index=pd.bdate_range("2010-01-01", periods=len(log)))


@pytest.mark.parametrize("horizon", [21,126,252])
def test_entire_slider_and_price_dependence(horizon):
    prepared = prepare_history(history())
    results = [estimate(prepared, price, horizon) for price in [1,10,50,100,300,500]]
    for r in results:
        assert r["supported"]
        assert 0 < r["probability"] < 1
        assert -1 < r["low_return"] < r["median_return"] < r["high_return"]
        assert r["ci_low"] <= r["probability"] <= r["ci_high"]
    assert len({round(r["probability"], 3) for r in results}) > 3
    assert results[0]["extrapolated"] and results[-1]["extrapolated"]
    count, curve = probability_curve(prepared, horizon)
    assert curve[0]["price"] == 1 and curve[-1]["price"] == 500
    assert count == fit_model(prepared,horizon)["count"]
    assert curve[0]["probability"] == results[0]["probability"]


def test_causal_features_and_missing_data():
    series = history()
    full = prepare_history(series)
    pd.testing.assert_frame_equal(full.iloc[:1000],prepare_history(series.iloc[:1000]))
    with pytest.raises(ValueError):
        estimate(full.iloc[:270],1,252)
    with pytest.raises(ValueError):
        estimate(full,501,21)
