import numpy as np
import pandas as pd

from price_scenario_validation import walk_forward, summarize, block_interval


def prices():
    rng = np.random.default_rng(19)
    return pd.Series(40*np.exp(np.cumsum(rng.normal(0, .015, 4200))),
                     index=pd.bdate_range("2010-01-01", periods=4200))


def test_future_mutation_does_not_change_forecasts():
    c = prices()
    a = walk_forward(c)
    cutoff = pd.Timestamp("2022-01-01")
    c.loc[c.index > cutoff] *= 1.8
    b = walk_forward(c)
    columns = ["origin", "horizon", "count", "baseline_count", "probability", "low",
               "high", "baseline_probability", "baseline_low", "baseline_high"]
    pd.testing.assert_frame_equal(a.loc[a.origin <= "2022-01-01", columns],
                                  b.loc[b.origin <= "2022-01-01", columns])


def test_fixed_calendars_maturity_and_paired_summary():
    c = prices()
    rows = walk_forward(c)
    for h, group in rows.groupby("horizon"):
        positions = c.index.get_indexer(pd.to_datetime(group.origin))
        assert np.all(np.diff(positions) == h)
        for row in group.itertuples():
            i = c.index.get_loc(row.origin)
            assert row.count <= (i-251)//h+1
            if row.status == "scored":
                assert row.count >= 10 and row.baseline_count >= 10
                assert row.end == str(c.index[i+h].date())
                recorded = group.loc[group.origin == row.origin, "return"].iloc[0]
                assert recorded == c.iloc[i+h]/c.iloc[i]-1
    summary, calibration = summarize(rows)
    for s in summary:
        assert s["scheduled"] == s["scored"] + s["unsupported"] + s["pending"]
        for label in ("matched", "unconditional"):
            assert sum(b["n"] for b in calibration if b["horizon"] == s["horizon"] and b["model"] == label) == s["scored"]
    assert block_interval([1]*5) == [None, None]
    assert block_interval([1]*10) == [1, 1]
