import numpy as np
import pandas as pd
import pytest

from price_scenario_model import prepare_history, estimate


def history():
    rng = np.random.default_rng(43)
    return pd.Series(40 * np.exp(np.cumsum(rng.normal(0, .025, 4000))),
                     index=pd.bdate_range("2010-01-01", periods=4000))


def test_scores_are_causal():
    closes = history()
    full, past = prepare_history(closes), prepare_history(closes.iloc[:1000])
    pd.testing.assert_series_equal(full["score"].iloc[:1000], past["score"])


def test_price_changes_conditioning_and_results():
    prepared = prepare_history(history())
    prices = np.linspace(max(1, prepared.close.min()), min(500, prepared.close.max()), 30)
    results = [estimate(prepared, p, 21) for p in prices]
    valid = [r for r in results if r["supported"]]
    assert len(valid) > 2
    assert len({r["probability"] for r in valid}) > 1
    assert results[0]["score"] < results[-1]["score"]
    for r in valid:
        assert 0 <= r["ci_low"] <= r["probability"] <= r["ci_high"] <= 1
        assert r["low_return"] <= r["median_return"] <= r["high_return"]
        assert r["count"] <= (len(prepared) - 251) // 21 + 1


def test_unsupported_and_invalid_inputs():
    prepared = prepare_history(history())
    assert not estimate(prepared, 500, 21)["supported"]
    assert estimate(prepared, 500, 21)["probability"] is None
    assert not estimate(prepare_history(history().iloc[:260]), 40, 252)["supported"]
    for value in (0, 501, np.nan):
        with pytest.raises(ValueError):
            estimate(prepared, value, 21)
    with pytest.raises(ValueError):
        estimate(prepared, 50, 20)


def test_only_completed_outcomes_and_nonoverlap():
    prepared = prepare_history(history())
    # Every date is a match, making the expected sample count exact.
    prepared["score"] = 50
    for column in prepared:
        if column.startswith("low:"):
            prepared[column] = 1
        if column.startswith("high:"):
            prepared[column] = 99
    result = estimate(prepared, 50, 252)
    assert result["count"] == len(range(0, len(prepared) - 252, 252))
    returns = (prepared.close.shift(-252) / prepared.close - 1).iloc[::252].dropna()
    assert result["median_return"] == pytest.approx(returns.median())
