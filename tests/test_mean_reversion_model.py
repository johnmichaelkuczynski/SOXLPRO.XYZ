import numpy as np
import pandas as pd
from mean_reversion_model import analyze, hurst_rs


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
