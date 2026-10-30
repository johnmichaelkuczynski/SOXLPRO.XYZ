import numpy as np
import pandas as pd
import pytest

from k_validation import (
    SCORES, assign_ranks, fit_cutoffs, nonoverlap_mask, outcomes, snapshots,
    summarize, validate_prices,
)
from mean_reversion_model import analyze


def prices(n=900):
    rng = np.random.default_rng(854)
    return pd.Series(np.exp(np.cumsum(rng.normal(.001, .025, n))) * 50,
                     index=pd.bdate_range("2016-01-01", periods=n), name="Close")


def test_features_match_requested_formula_and_are_causal():
    p = prices()
    features = snapshots(p)
    for row in features.iloc[::30].itertuples():
        live = analyze(p.iloc[:row.position+1].to_frame())
        for research, current in (("k_edge", "k_edge"), ("k_signed", "k_signed"),
                                  ("reversion", "score"), ("trend", "trend")):
            assert getattr(row, research) == pytest.approx(live[current])
        assert row.label == live["k_label"]
    mutated = p.copy()
    mutated.iloc[700:] *= 12
    pd.testing.assert_frame_equal(features.loc[features.position < 700],
                                  snapshots(mutated).query("position < 700"))


def test_training_ranks_do_not_use_holdout_and_never_split_ties():
    features = snapshots(prices(1200))
    frozen = fit_cutoffs(features)
    changed = features.copy()
    changed.loc[changed.date >= "2019-01-01", list(SCORES)] = 1e9
    assert fit_cutoffs(changed) == frozen
    equal = pd.DataFrame({name: [0., 0., 1., np.nan] for name in SCORES})
    ranked = assign_ranks(equal, {name: [0., 0.] for name in SCORES})
    assert ranked.k_edge_rank.tolist() == ["Low", "Low", "High", None]


def test_outcomes_next_close_and_full_path_drawdown_and_purge():
    p = pd.Series([100., 110., 120., 90., 99.],
                  index=pd.bdate_range("2018-12-27", periods=5))
    f = pd.DataFrame([dict(position=0, date=p.index[0])])
    result = outcomes(p, f, 3).iloc[0]
    assert result.entry_date == p.index[1]
    assert result.return_pct == pytest.approx(-10)
    assert result.drawdown_pct == pytest.approx(-25)
    assert result.partition == "purged"
    assert outcomes(p, f, 4).empty


def test_nonoverlapping_intervals_do_not_share_entry_or_exit():
    dates = pd.bdate_range("2020-01-01", periods=20)
    f = pd.DataFrame({"entry_date": dates[:10], "end_date": dates[5:15]})
    assert np.flatnonzero(nonoverlap_mask(f)).tolist() == [0, 6]


def test_empty_groups_small_samples_and_paired_baselines():
    p = prices(1400)
    features = assign_ranks(snapshots(p), {name: [0, 0] for name in SCORES})
    frame = outcomes(p, features, 21)
    summary, comparisons = summarize(frame, 21, replicates=100)
    assert len(summary) == 21
    empty = summary.loc[summary.group == "k_edge: Middle"].iloc[0]
    assert empty["count"] == 0
    assert np.isnan(empty.mean_return_pct)
    sparse = comparisons.loc[comparisons.group == "k_edge: Middle"]
    assert sparse.return_ci_low.isna().all()
    assert sparse.status.str.startswith("Insufficient").all()
    # Shared resampling must produce exactly zero for identical selectors.
    frame.loc[:, "trend_rank"] = "High"
    frame.loc[:, "reversion_rank"] = "High"
    _, comparison = summarize(frame, 5, replicates=100)
    paired = comparison.query("group == 'trend: High' and baseline == 'reversion: High'").iloc[0]
    assert paired.return_difference_pp == 0
    assert paired.return_ci_low == 0
    assert paired.return_ci_high == 0


def test_invalid_prices_fail_explicitly():
    for p in (prices(99), prices().iloc[::-1], pd.concat([prices(), prices()])):
        with pytest.raises(ValueError):
            validate_prices(p)
    p = prices()
    p.iloc[0] = np.inf
    with pytest.raises(ValueError):
        snapshots(p)
    with pytest.raises(ValueError, match="No matured"):
        summarize(pd.DataFrame(), 21)
