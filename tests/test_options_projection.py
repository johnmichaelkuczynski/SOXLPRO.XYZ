from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch, Mock
import numpy as np
import pandas as pd
import pytest
from options_projection_model import price, project
from options_projection_data import load_chain, OptionsDataError


def fixture():
    now = datetime(2026, 10, 26, 12, tzinfo=ZoneInfo("America/New_York"))
    history = pd.DataFrame({"Close": 30*np.exp(np.cumsum(np.random.default_rng(1).normal(.001,.04,1000)))})
    contract = dict(expiration="2026-11-20", type="call", strike=80, spot=85, iv=.8,
                    quote_time=now.isoformat(), spot_time=now.isoformat(), multiplier=100)
    return now, history, contract


def test_expiry_intrinsic_and_put_call_parity():
    assert np.allclose(price([70,80,90],80,0,.8,.04,0,"call"), [0,0,10])
    assert np.allclose(price([70,80,90],80,0,.8,.04,0,"put"), [10,0,0])
    c = price(85,80,.5,.8,.04,.01,"call")
    p = price(85,80,.5,.8,.04,.01,"put")
    assert c-p == pytest.approx(85*np.exp(-.01*.5)-80*np.exp(-.04*.5))


@pytest.mark.parametrize("kind", ["call", "put"])
def test_projection_finite_bands_and_position_pl(kind):
    now, history, contract = fixture()
    contract["type"] = kind
    result = project(history, contract, 8, now.date()+timedelta(days=10), now=now)
    assert result["quantiles"].shape[0] == 5
    assert np.all(np.isfinite(result["quantiles"]))
    assert np.all(np.diff(result["quantiles"],axis=0) >= 0)
    assert np.all(result["quantiles"] >= 0)
    assert 0 <= result["horizon_profit_probability"] <= 1
    assert result["dates"][-1].date().isoformat() == contract["expiration"]
    assert np.allclose(result["horizon_profit_quantiles"],
                       (result["quantiles"][:,result["horizon_index"]]-8)*100)
    assert result["path_high95"] >= result["path_low05"]


def test_missing_iv_adjusted_expired_stale_rejected():
    now, history, contract = fixture()
    for changes in ({"iv":None}, {"adjusted":True}, {"expiration":"2025-01-01"},
                    {"quote_time":"2025-01-01T00:00:00Z"}, {"spot_time":None}):
        with pytest.raises(ValueError):
            project(history, dict(contract, **changes),8,now.date()+timedelta(days=2),now=now)


def test_no_key_or_entitlement_fails_explicitly():
    load_chain.clear()
    with patch.dict("os.environ", {"POLYGON_API_KEY":""}):
        with pytest.raises(OptionsDataError, match="not connected"):
            load_chain(datetime(2026,11,20).date(),"call")
    with patch.dict("os.environ", {"POLYGON_API_KEY":"test_only"}), \
         patch("options_projection_data.requests.get", return_value=Mock(status_code=403)):
        with pytest.raises(OptionsDataError, match="entitlements"):
            load_chain(datetime(2026,11,20).date(),"call")
