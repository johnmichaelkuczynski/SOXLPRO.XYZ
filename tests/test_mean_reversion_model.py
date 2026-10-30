import numpy as np
import pandas as pd
from mean_reversion_model import analyze, hurst_rs, trend_metrics, k_label


def frame(values):
    return pd.DataFrame({"Close": values}, index=pd.bdate_range("2020-01-01", periods=len(values)))


def test_missing_constant_and_score():
    assert analyze(frame(np.ones(99)))["H"] is None
    assert analyze(frame(np.ones(252)))["score"] is None
    rng = np.random.default_rng(10)
    result = analyze(frame(np.exp(np.cumsum(rng.normal(0,.02,500)))))
    assert result["count"] == 252
    assert result["score"] == np.clip((.5-result["H"])*200,0,100)


def test_direction_and_half_life():
    rng = np.random.default_rng(12)
    x = [100.]
    for _ in range(499):
        x.append(100 + .8*(x[-1]-100) + rng.normal())
    result = analyze(frame(x), 500)
    assert result["half_life"] > 0
    assert hurst_rs(x) < hurst_rs(np.exp(np.cumsum(rng.normal(0,.02,500))))


def test_trend_requires_full_comparison_and_is_independent():
    import pytest
    prices = frame(np.arange(1., 501.))
    assert analyze(prices.iloc[:199])["golden_cross"] is None
    assert analyze(prices.iloc[:259])["trend"] is None
    assert analyze(prices.iloc[:259])["H"] is not None
    result = analyze(prices)
    expected = (np.mean(np.arange(301.,501.))/np.mean(np.arange(241.,441.))-1)*100
    assert result["slope"] == pytest.approx(expected)
    assert result["trend"] == 100
    assert result["golden_cross"] is True
    assert result["trend"] == analyze(prices, 100)["trend"]
    assert trend_metrics(prices.Close[::-1].reset_index(drop=True))["trend"] == -100
    assert analyze(frame(np.ones(300)))["trend"] == 0
    for signed, prefix in [(70,"Prime"),(40,"Good"),(.1,"Weak"),(0,"No Edge"),
                           (-.1,"Caution"),(-40,"Value Trap"),(-70,"Avoid")]:
        assert k_label(signed,1).startswith(prefix)
    assert k_label(0,0) == "No Edge: Flat"


def test_k_synthesis():
    from unittest.mock import patch
    with patch("mean_reversion_model._reversion", return_value={"score":80.}):
        result = analyze(frame(np.arange(500.,0.,-1.)))
    assert result["k_signed"] == -80 and result["k_edge"] == 0
    assert result["k_label"].startswith("Avoid")
