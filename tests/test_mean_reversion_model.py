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


def test_simulation_replica_matches_production_estimator():
    from hurst_uncertainty import rs_batch, fractional_gaussian_increments, WINDOWS
    for n in WINDOWS:
        for h in (.3, .5, .7):
            increments = fractional_gaussian_increments(np.random.default_rng(42), 8, n, h)
            prices = np.exp(np.column_stack([np.zeros(8), np.cumsum(increments*.01, axis=1)]))
            np.testing.assert_allclose(rs_batch(increments), [hurst_rs(p) for p in prices], atol=1e-11)


def test_reference_bias_uncertainty_and_independent_detection():
    from hurst_uncertainty import load_reference, WINDOWS
    data = load_reference()
    for n in WINDOWS:
        rows = {r["true_h"]: r for r in data["summary"] if r["closes"] == n}
        assert rows[.3]["mean"] < rows[.5]["mean"] < rows[.7]["mean"]
        assert .05 < rows[.5]["bias"] < .18
        assert .015 < rows[.5]["evidence_rate"] < .075
        assert rows[.3]["evidence_rate"] > .4
        for r in rows.values():
            assert r["increments"] == n - 1
            assert r["sampling_95"][0] < r["mean"] < r["sampling_95"][1]
            assert r["sd"] > 0 and r["rmse"] >= abs(r["bias"])
    assert data["summary"][0]["sd"] > data["summary"][-3]["sd"]


def test_evidence_tails_boundaries_and_unavailable():
    from hurst_uncertainty import hurst_evidence, load_reference
    null = np.asarray(load_reference()["null_samples"]["100"])
    for h in (.2, .48, .5, .8):
        evidence = hurst_evidence(h, 100)
        assert evidence["p_lower"] == (1 + (null <= h).sum()) / (len(null) + 1)
        assert (evidence["label"] == "Anti-persistence evidence") == (h < .5 and evidence["p_lower"] <= .05)
    assert hurst_evidence(-.1, 100)["p_lower"] > 0
    assert hurst_evidence(1.2, 100)["p_lower"] == 1
    for h, count in [(None, 100), (np.nan, 252), (.3, 200), (.3, 99)]:
        assert hurst_evidence(h, count)["label"] == "N/A"
        assert hurst_evidence(h, count)["reason"]


def test_missing_or_stale_reference_is_explicit():
    from unittest.mock import patch
    from hurst_uncertainty import hurst_evidence, load_reference
    import pytest
    load_reference.cache_clear()
    try:
        with patch("hurst_uncertainty.estimator_fingerprint", return_value="changed"):
            with pytest.raises(ValueError, match="estimator changed"):
                load_reference()
            assert "outdated" in hurst_evidence(.2, 100)["reason"]
        with patch("hurst_uncertainty.REFERENCE") as path:
            path.read_text.side_effect = FileNotFoundError
            assert hurst_evidence(.2, 100)["label"] == "N/A"
    finally:
        load_reference.cache_clear()


def test_evidence_preserves_scores_half_life_and_uses_actual_count():
    from mean_reversion_model import _reversion
    values = np.exp(np.cumsum(np.random.default_rng(19).normal(0, .01, 252)))
    original = _reversion(frame(values), 500)
    result = analyze(frame(values), 500)
    for key in original:
        assert original[key] == result[key]
    assert result["hurst_evidence"]["simulations"] == 2000
    assert result["count"] == 252
    assert analyze(frame(values[:200]), 500)["hurst_evidence"]["label"] == "N/A"
    assert analyze(frame(np.ones(252)))["hurst_evidence"]["label"] == "N/A"


def test_evidence_table_renders_without_changing_existing_controls():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string("""
import numpy as np
import pandas as pd
from mean_reversion_ui import render_mean_reversion
prices = np.exp(np.cumsum(np.random.default_rng(10).normal(0, .02, 500)))
render_mean_reversion({"TEST": pd.DataFrame({"Close": prices},
    index=pd.bdate_range("2020-01-01", periods=500))})
""").run()
    assert not app.exception
    table = app.dataframe[0].value
    assert "Hurst evidence" in table and "Evidence details" in table
    assert "Lower-tail p=" in table.iloc[0]["Evidence details"]
    app.number_input[0].set_value(200).run()
    assert not app.exception
    assert app.dataframe[0].value.iloc[0]["Hurst evidence"] == "N/A"
