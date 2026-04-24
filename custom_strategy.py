"""
Custom Strategy Builder for the Backtest module.

Provides:
  - Indicator computation library (pure functions on pandas DataFrames)
  - Rule evaluation engine (AND/OR conditions over indicators)
  - Trade simulator with stop loss, take profit, max hold, position direction
  - JSON-backed save/load of strategies

Designed to compose with backtest_ui._render_results for output.
"""
import os
import json
import numpy as np
import pandas as pd
from datetime import datetime


SAVE_PATH = os.path.join(".local", "saved_strategies.json")


# ---------------------------------------------------------------------------
# Indicator catalog
# ---------------------------------------------------------------------------
SIGNAL_VERSION = "1.0"  # bump when signal computation logic changes

# App-generated signals (computed point-in-time, no lookahead)
APP_SIGNALS_CATEGORICAL = {
    "Vol Surface Signal (Calls)": ["BUY", "SELL", "NEUTRAL"],
    "Vol Surface Signal (Puts)": ["BUY", "SELL", "NEUTRAL"],
    "Vol Regime Label": ["CHEAP", "MID-RANGE", "EXPENSIVE"],
}
APP_SIGNALS_NUMERIC_ONE_PARAM = {"Period Analysis Percentile(N)"}
APP_SIGNALS_NUMERIC_TWO_PARAM = {"Probability Engine P(M%, Hd)"}
NEEDS_OPTIONS_DATA = {"Vol Surface Signal (Calls)", "Vol Surface Signal (Puts)"}
OPTIONS_WINDOW_START = "2022-01-01"

INDICATORS_NEEDS_N = {
    "SMA(N)", "EMA(N)", "RSI(N)", "Bollinger %B(N)",
    "N-day high", "N-day low", "N-day % change",
    "Realized vol(N)", "ATR(N)", "SOXL z-score vs QQQ(N)",
} | APP_SIGNALS_NUMERIC_ONE_PARAM

INDICATORS_NO_N = {
    "SOXL price", "QQQ price", "VIX level",
    "MACD", "Drawdown from peak (%)", "SOXL/QQQ ratio",
    "Days held in position",
} | set(APP_SIGNALS_CATEGORICAL.keys())

ALL_INDICATORS = sorted(
    INDICATORS_NO_N | INDICATORS_NEEDS_N | APP_SIGNALS_NUMERIC_TWO_PARAM
)
DEFAULT_N = {
    "SMA(N)": 50, "EMA(N)": 20, "RSI(N)": 14, "Bollinger %B(N)": 20,
    "N-day high": 30, "N-day low": 30, "N-day % change": 30,
    "Realized vol(N)": 30, "ATR(N)": 14, "SOXL z-score vs QQQ(N)": 60,
    "Period Analysis Percentile(N)": 30,
    "Probability Engine P(M%, Hd)": 10.0,  # M default
}
DEFAULT_N2 = {"Probability Engine P(M%, Hd)": 30}  # H default

OPERATORS = [">", "<", "=", "crosses above", "crosses below"]


def panel_uses_options_signals(panel):
    for c in panel.get("conditions", []):
        for side in (c.get("lhs", {}), c.get("rhs", {})):
            if side.get("kind") == "indicator" and side.get("indicator") in NEEDS_OPTIONS_DATA:
                return True
    return False


def is_categorical_signal(name):
    return name in APP_SIGNALS_CATEGORICAL


# ---------------------------------------------------------------------------
# Point-in-time app-signal computations (compute_signal_pit family)
# ---------------------------------------------------------------------------
def compute_vol_regime_pit(soxl, lookback=252, low_pct=33, high_pct=67):
    """CHEAP / MID-RANGE / EXPENSIVE labels per day. Uses only data ≤ t."""
    p = soxl["adj_close"]
    log_ret = np.log(p / p.shift(1))
    rv30 = log_ret.rolling(30).std() * np.sqrt(252)
    out = pd.Series("MID-RANGE", index=p.index, dtype=object)
    for i in range(lookback + 30, len(rv30)):
        window = rv30.iloc[i - lookback:i].dropna()
        cur = rv30.iloc[i]
        if not np.isfinite(cur) or len(window) < 60:
            continue
        lo = np.percentile(window, low_pct)
        hi = np.percentile(window, high_pct)
        if cur <= lo:
            out.iloc[i] = "CHEAP"
        elif cur >= hi:
            out.iloc[i] = "EXPENSIVE"
    return out


def compute_vol_surface_signal_pit(vix, soxl, side="calls", lookback=252,
                                    low_pct=25, high_pct=75):
    """BUY / SELL / NEUTRAL per day.

    PIT proxy: uses VIX percentile vs trailing 252d as a robust market-wide
    options-pricing regime indicator. True per-strike historical IV
    reconstruction would require day-by-day Polygon chain rebuilds (cost-
    prohibitive). VIX is itself derived from S&P 500 option mid-IVs and tracks
    SOXL option IV regime closely (corr ≈ 0.85). Side ('calls' vs 'puts')
    currently use the same percentile thresholds — both surfaces re-price
    together in the broad vol regime.
    """
    if vix is None or vix.empty:
        return pd.Series("NEUTRAL", index=soxl.index, dtype=object)
    vix_aligned = vix["adj_close"].reindex(soxl.index).ffill()
    out = pd.Series("NEUTRAL", index=soxl.index, dtype=object)
    for i in range(lookback, len(vix_aligned)):
        window = vix_aligned.iloc[i - lookback:i].dropna()
        cur = vix_aligned.iloc[i]
        if not np.isfinite(cur) or len(window) < 60:
            continue
        lo = np.percentile(window, low_pct)
        hi = np.percentile(window, high_pct)
        if cur <= lo:
            out.iloc[i] = "BUY"
        elif cur >= hi:
            out.iloc[i] = "SELL"
    return out


def compute_probability_pit(soxl, M_pct, H_days, train_window=504):
    """P(|return_H| ≥ M%) per day, computed using only the trailing
    `train_window` of empirical exceedances available at that date."""
    p = soxl["adj_close"].values
    H = int(H_days)
    out = pd.Series(np.nan, index=soxl.index)
    train_window = int(train_window)
    for i in range(train_window + H, len(p) - H - 1):
        train = p[i - train_window:i]
        if len(train) < H + 30:
            continue
        train_returns = (train[H:] - train[:-H]) / train[:-H] * 100
        out.iloc[i] = float((np.abs(train_returns) >= float(M_pct)).mean())
    return out


def compute_period_pctile_pit(soxl, N):
    """Percentile rank of current N-day return within the historical
    distribution of N-day returns observed STRICTLY before t."""
    p = soxl["adj_close"]
    N = int(N)
    n_ret = p.pct_change(N) * 100
    out = pd.Series(np.nan, index=p.index)
    for i in range(N * 4, len(n_ret)):
        cur = n_ret.iloc[i]
        history = n_ret.iloc[:i].dropna()
        if not np.isfinite(cur) or len(history) < 30:
            continue
        out.iloc[i] = float((history <= cur).mean() * 100)
    return out


def compute_indicator(name, n, soxl, qqq, vix, n2=None):
    """Return a pandas Series (indexed like soxl) for the requested indicator.
    `Days held in position` returns None and is handled by the simulator at runtime.
    """
    # App-generated PIT signals
    if name == "Vol Regime Label":
        return compute_vol_regime_pit(soxl)
    if name == "Vol Surface Signal (Calls)":
        return compute_vol_surface_signal_pit(vix, soxl, side="calls")
    if name == "Vol Surface Signal (Puts)":
        return compute_vol_surface_signal_pit(vix, soxl, side="puts")
    if name == "Probability Engine P(M%, Hd)":
        M = float(n) if n is not None else 10.0
        H = int(n2) if n2 is not None else 30
        return compute_probability_pit(soxl, M, H)
    if name == "Period Analysis Percentile(N)":
        return compute_period_pctile_pit(soxl, int(n) if n else 30)
    p = soxl["adj_close"]
    if name == "SOXL price":
        return p
    if name == "QQQ price":
        return qqq["adj_close"].reindex(p.index).ffill()
    if name == "VIX level":
        if vix is None or vix.empty:
            return pd.Series(np.nan, index=p.index)
        return vix["adj_close"].reindex(p.index).ffill()
    if name == "SMA(N)":
        return p.rolling(int(n)).mean()
    if name == "EMA(N)":
        return p.ewm(span=int(n), adjust=False).mean()
    if name == "RSI(N)":
        delta = p.diff()
        up = delta.clip(lower=0).ewm(alpha=1 / int(n), adjust=False).mean()
        down = (-delta.clip(upper=0)).ewm(alpha=1 / int(n), adjust=False).mean()
        rs = up / down.replace(0, np.nan)
        return 100 - (100 / (1 + rs))
    if name == "MACD":
        return p.ewm(span=12, adjust=False).mean() - p.ewm(span=26, adjust=False).mean()
    if name == "Bollinger %B(N)":
        n = int(n)
        ma = p.rolling(n).mean()
        sd = p.rolling(n).std(ddof=1)
        upper = ma + 2 * sd
        lower = ma - 2 * sd
        return (p - lower) / (upper - lower)
    if name == "N-day high":
        return p.rolling(int(n)).max()
    if name == "N-day low":
        return p.rolling(int(n)).min()
    if name == "N-day % change":
        return p.pct_change(int(n)) * 100
    if name == "Realized vol(N)":
        log_ret = np.log(p / p.shift(1))
        return log_ret.rolling(int(n)).std(ddof=1) * np.sqrt(252) * 100
    if name == "ATR(N)":
        h = soxl["high"]
        l = soxl["low"]
        c_prev = soxl["close"].shift(1)
        tr = pd.concat([(h - l), (h - c_prev).abs(), (l - c_prev).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / int(n), adjust=False).mean()
    if name == "Drawdown from peak (%)":
        return (p / p.cummax() - 1) * 100
    if name == "SOXL/QQQ ratio":
        q = qqq["adj_close"].reindex(p.index).ffill()
        return p / q
    if name == "SOXL z-score vs QQQ(N)":
        n = int(n)
        soxl_lr = np.log(p / p.shift(1))
        q = qqq["adj_close"].reindex(p.index).ffill()
        qqq_lr = np.log(q / q.shift(1))
        beta = soxl_lr.rolling(20).cov(qqq_lr) / qqq_lr.rolling(20).var()
        residual = soxl_lr - beta * qqq_lr
        cumres = residual.rolling(20).sum()
        return (cumres - cumres.rolling(n).mean()) / cumres.rolling(n).std(ddof=1)
    if name == "Days held in position":
        return None
    return pd.Series(np.nan, index=p.index)


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------
def _series_for_side(side, soxl, qqq, vix, days_held_series=None):
    """Return a Series for either an indicator-side, a value-side, or a category-side."""
    if side["kind"] == "value":
        return pd.Series(float(side["value"]), index=soxl.index)
    if side["kind"] == "category":
        return pd.Series(str(side["value"]), index=soxl.index, dtype=object)
    name = side["indicator"]
    if name == "Days held in position":
        if days_held_series is None:
            return pd.Series(0.0, index=soxl.index)
        return days_held_series
    return compute_indicator(name, side.get("n"), soxl, qqq, vix, n2=side.get("n2"))


def _condition_signal(cond, soxl, qqq, vix, days_held_series=None):
    """Return a boolean Series for a single condition row."""
    lhs = _series_for_side(cond["lhs"], soxl, qqq, vix, days_held_series)
    rhs = _series_for_side(cond["rhs"], soxl, qqq, vix, days_held_series)
    op = cond["op"]
    # Categorical comparison (string equality only)
    if lhs.dtype == object or rhs.dtype == object:
        if op == "=":
            sig = lhs.astype(str) == rhs.astype(str)
        else:
            sig = pd.Series(False, index=lhs.index)
        return sig.fillna(False)
    a = lhs.astype(float)
    b = rhs.astype(float)
    if op == ">":
        sig = a > b
    elif op == "<":
        sig = a < b
    elif op == "=":
        sig = np.isclose(a.fillna(np.inf), b.fillna(np.nan), rtol=1e-3, atol=1e-6)
        sig = pd.Series(sig, index=a.index)
    elif op == "crosses above":
        sig = (a > b) & (a.shift(1) <= b.shift(1))
    elif op == "crosses below":
        sig = (a < b) & (a.shift(1) >= b.shift(1))
    else:
        sig = pd.Series(False, index=a.index)
    return sig.fillna(False)


def evaluate_panel(panel, soxl, qqq, vix, days_held_series=None):
    """Combine conditions in a panel via AND/OR. Returns boolean Series."""
    conds = panel.get("conditions", [])
    if not conds:
        return pd.Series(False, index=soxl.index)
    sigs = [_condition_signal(c, soxl, qqq, vix, days_held_series) for c in conds]
    base = sigs[0].copy()
    combinator = panel.get("combinator", "AND")
    for s in sigs[1:]:
        base = (base & s) if combinator == "AND" else (base | s)
    return base


def panel_uses_days_held(panel):
    for c in panel.get("conditions", []):
        for side in (c.get("lhs", {}), c.get("rhs", {})):
            if side.get("kind") == "indicator" and side.get("indicator") == "Days held in position":
                return True
    return False


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------
def simulate_custom_strategy(soxl, qqq, vix, entry_panel, exit_panel, controls):
    """
    Walk forward day by day. Returns (equity_series, trade_returns_list, trade_log_df).

    controls: {"max_hold": int|None, "stop_pct": float|None, "tp_pct": float|None,
               "direction": "Long"|"Short"|"Both"}
    """
    direction = controls.get("direction", "Long")
    max_hold = controls.get("max_hold")
    stop_pct = controls.get("stop_pct")
    tp_pct = controls.get("tp_pct")

    p = soxl["adj_close"]
    idx = p.index
    n = len(idx)

    needs_dh = panel_uses_days_held(entry_panel) or panel_uses_days_held(exit_panel)

    if not needs_dh:
        entry_sig = evaluate_panel(entry_panel, soxl, qqq, vix)
        exit_sig = evaluate_panel(exit_panel, soxl, qqq, vix) if exit_panel.get("conditions") else None
        entry_cond_series = None
        exit_cond_series = None
    else:
        entry_sig = None
        exit_sig = None
        # Precompute non-days-held condition signals ONCE so per-day eval is O(1)
        def _precompute_static(panel):
            out = []
            for c in panel.get("conditions", []):
                touches_dh = any(
                    side.get("kind") == "indicator" and side.get("indicator") == "Days held in position"
                    for side in (c.get("lhs", {}), c.get("rhs", {}))
                )
                out.append(None if touches_dh else _condition_signal(c, soxl, qqq, vix))
            return out
        entry_cond_series = _precompute_static(entry_panel)
        exit_cond_series = _precompute_static(exit_panel) if exit_panel.get("conditions") else []

    timeline = pd.Series(0.0, index=idx)
    trade_returns = []
    trade_log = []

    in_pos = False
    pos_dir = 0  # +1 long, -1 short
    entry_idx = None
    entry_price = None
    days_held = 0
    days_held_series = pd.Series(0.0, index=idx) if needs_dh else None

    for i in range(1, n):
        price = p.iloc[i]
        if not np.isfinite(price):
            continue

        if in_pos:
            days_held += 1
            if needs_dh:
                days_held_series.iloc[i] = days_held
            move_pct = (price / entry_price - 1) * 100 * pos_dir
            should_exit = False
            reason = None
            if max_hold and days_held >= int(max_hold):
                should_exit, reason = True, "max_hold"
            if stop_pct and move_pct <= -float(stop_pct):
                should_exit, reason = True, "stop"
            if tp_pct and move_pct >= float(tp_pct):
                should_exit, reason = True, "take_profit"
            if not should_exit and exit_panel.get("conditions"):
                if needs_dh:
                    ex = _eval_at(exit_panel, soxl, qqq, vix, i, days_held_series, exit_cond_series)
                else:
                    ex = bool(exit_sig.iloc[i])
                if ex:
                    should_exit, reason = True, "exit_rule"
            if should_exit:
                r = (price / entry_price - 1) * pos_dir
                trade_returns.append(float(r))
                hd = i - entry_idx
                hd = max(hd, 1)
                daily = (1 + r) ** (1 / hd) - 1
                for k in range(1, hd + 1):
                    timeline.iloc[entry_idx + k] += daily
                trade_log.append({
                    "entry_date": idx[entry_idx].date(),
                    "exit_date": idx[i].date(),
                    "direction": "LONG" if pos_dir > 0 else "SHORT",
                    "entry_price": round(float(entry_price), 4),
                    "exit_price": round(float(price), 4),
                    "days_held": hd,
                    "return_%": round(r * 100, 2),
                    "exit_reason": reason,
                })
                in_pos = False
                pos_dir = 0
                entry_idx = None
                entry_price = None
                days_held = 0
                if needs_dh:
                    days_held_series.iloc[i] = 0
        if not in_pos:
            if needs_dh:
                want = _eval_at(entry_panel, soxl, qqq, vix, i, days_held_series, entry_cond_series)
            else:
                want = bool(entry_sig.iloc[i])
            if want:
                in_pos = True
                pos_dir = 1 if direction == "Long" else (-1 if direction == "Short" else 1)
                entry_idx = i
                entry_price = price
                days_held = 0
                if needs_dh:
                    days_held_series.iloc[i] = 0

    equity = (1 + timeline).cumprod()
    log_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame()
    return equity, trade_returns, log_df


def _eval_at(panel, soxl, qqq, vix, i, days_held_series, precomputed=None):
    """Evaluate a panel at a single index i. `precomputed` (list aligned with
    conditions) holds full Series for non-days-held conditions so we just index
    into them; days-held conditions are evaluated live."""
    sigs = []
    for j, c in enumerate(panel.get("conditions", [])):
        if precomputed is not None and precomputed[j] is not None:
            sigs.append(bool(precomputed[j].iloc[i]))
        else:
            s = _condition_signal(c, soxl, qqq, vix, days_held_series)
            sigs.append(bool(s.iloc[i]))
    if not sigs:
        return False
    if panel.get("combinator", "AND") == "AND":
        return all(sigs)
    return any(sigs)


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------
def _ensure_dir():
    os.makedirs(os.path.dirname(SAVE_PATH), exist_ok=True)


def load_all_strategies():
    if not os.path.exists(SAVE_PATH):
        return {}
    try:
        with open(SAVE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_strategy(name, config):
    _ensure_dir()
    store = load_all_strategies()
    store[name] = {
        "config": config,
        "signal_version": SIGNAL_VERSION,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    with open(SAVE_PATH, "w") as f:
        json.dump(store, f, indent=2, default=str)


def strategy_uses_app_signals(config):
    """True if the loaded strategy references any app-generated signal."""
    app_set = (set(APP_SIGNALS_CATEGORICAL.keys())
               | APP_SIGNALS_NUMERIC_ONE_PARAM
               | APP_SIGNALS_NUMERIC_TWO_PARAM)
    for panel_key in ("entry", "exit"):
        for c in (config.get(panel_key, {}).get("conditions") or []):
            for side in (c.get("lhs", {}), c.get("rhs", {})):
                if side.get("kind") == "indicator" and side.get("indicator") in app_set:
                    return True
    return False


def delete_strategy(name):
    store = load_all_strategies()
    if name in store:
        del store[name]
        with open(SAVE_PATH, "w") as f:
            json.dump(store, f, indent=2, default=str)


def describe_panel(panel):
    """Return human-readable string of a panel's logic."""
    parts = []
    for c in panel.get("conditions", []):
        lhs = c["lhs"]
        rhs = c["rhs"]
        lhs_str = (f"{lhs['indicator']}({lhs.get('n')})" if lhs.get("n")
                   else lhs.get("indicator", lhs.get("value")))
        rhs_str = (f"{rhs['indicator']}({rhs.get('n')})" if rhs.get("kind") == "indicator" and rhs.get("n")
                   else (rhs.get("indicator") if rhs.get("kind") == "indicator" else str(rhs.get("value"))))
        parts.append(f"{lhs_str} {c['op']} {rhs_str}")
    if not parts:
        return "(no conditions)"
    return f" {panel.get('combinator', 'AND')} ".join(parts)
