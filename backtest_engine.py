import numpy as np
import pandas as pd
import plotly.graph_objects as go


TRADING_DAYS = 252


def equity_curve_from_returns(returns):
    return (1.0 + pd.Series(returns).fillna(0.0)).cumprod()


def buy_and_hold_curve(price_series):
    s = price_series.dropna()
    if s.empty:
        return pd.Series(dtype=float)
    return s / s.iloc[0]


def compute_stats(equity, returns=None, n_trades=None):
    eq = pd.Series(equity).dropna()
    if eq.empty or len(eq) < 2:
        return {}
    n_days = len(eq)
    total_ret = float(eq.iloc[-1] / eq.iloc[0] - 1)
    years = n_days / TRADING_DAYS
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years > 0 else 0.0
    rolling_max = eq.cummax()
    dd = eq / rolling_max - 1
    max_dd = float(dd.min())
    if returns is None:
        returns = eq.pct_change().dropna()
    rstd = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    sharpe = (np.mean(returns) / rstd * np.sqrt(TRADING_DAYS)) if rstd > 0 else 0.0
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    hit_rate = len(wins) / len(returns) * 100 if len(returns) else 0.0
    avg_win = float(np.mean(wins)) * 100 if wins else 0.0
    avg_loss = float(np.mean(losses)) * 100 if losses else 0.0
    return {
        "total_return_%": round(total_ret * 100, 2),
        "CAGR_%": round(cagr * 100, 2),
        "max_drawdown_%": round(max_dd * 100, 2),
        "Sharpe": round(sharpe, 2),
        "hit_rate_%": round(hit_rate, 1),
        "avg_win_%": round(avg_win, 2),
        "avg_loss_%": round(avg_loss, 2),
        "trades": int(n_trades) if n_trades is not None else int(len(returns)),
    }


def random_entry_baseline(price_series, n_trades, holding_days, seed=42):
    """Pick n_trades random entry dates, hold for holding_days, compound."""
    rng = np.random.default_rng(seed)
    s = price_series.dropna()
    if len(s) < holding_days + 5 or n_trades < 1:
        return pd.Series(dtype=float), []
    max_idx = len(s) - holding_days - 1
    entry_idxs = sorted(rng.choice(max_idx, size=min(n_trades, max_idx), replace=False))
    trade_returns = []
    timeline = pd.Series(0.0, index=s.index)
    for i in entry_idxs:
        entry = s.iloc[i]
        exit_ = s.iloc[i + holding_days]
        r = exit_ / entry - 1
        trade_returns.append(float(r))
        # spread the trade return across its holding days as daily compounded
        daily = (1 + r) ** (1 / holding_days) - 1
        for k in range(1, holding_days + 1):
            timeline.iloc[i + k] += daily
    eq = (1 + timeline).cumprod()
    return eq, trade_returns


def render_equity_chart(curves, title="Backtest Equity Curves"):
    """curves: dict of name -> pd.Series indexed by date."""
    fig = go.Figure()
    colors = {
        "Strategy": "#1976D2",
        "SOXL Buy & Hold": "#D32F2F",
        "QQQ Buy & Hold": "#43A047",
        "Random Entry Baseline": "#888888",
    }
    for name, series in curves.items():
        if series is None or len(series) == 0:
            continue
        dash = "dot" if "Random" in name else "solid"
        fig.add_trace(go.Scatter(
            x=series.index, y=series.values,
            name=name, mode="lines",
            line=dict(color=colors.get(name, "#555"), width=2.2, dash=dash),
        ))
    fig.update_layout(
        title=title, height=460, template="plotly_white",
        margin=dict(l=40, r=20, t=50, b=40),
        yaxis=dict(title="Growth of $1", tickformat=".2f"),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="center", x=0.5),
        hovermode="x unified",
    )
    return fig


def calibration_curve(predicted_probs, realized_outcomes, n_bins=10):
    """Returns (bin_centers, predicted_means, realized_means, counts) and Brier score."""
    p = np.asarray(predicted_probs, dtype=float)
    y = np.asarray(realized_outcomes, dtype=float)
    mask = np.isfinite(p) & np.isfinite(y)
    p, y = p[mask], y[mask]
    if len(p) == 0:
        return None, None, None, None, np.nan
    edges = np.linspace(0, 1, n_bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    pred_means, real_means, counts = [], [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (p >= lo) & (p < hi if hi < 1 else p <= hi)
        if mask.sum() == 0:
            pred_means.append(np.nan)
            real_means.append(np.nan)
            counts.append(0)
            continue
        pred_means.append(float(p[mask].mean()))
        real_means.append(float(y[mask].mean()))
        counts.append(int(mask.sum()))
    brier = float(np.mean((p - y) ** 2))
    return centers, pred_means, real_means, counts, brier


def render_calibration_chart(predicted_probs, realized_outcomes, n_bins=10):
    centers, pred, real, counts, brier = calibration_curve(predicted_probs, realized_outcomes, n_bins)
    if centers is None:
        return None, np.nan
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[0, 1], y=[0, 1], mode="lines",
        line=dict(color="#888", dash="dash"), name="Perfect calibration",
    ))
    fig.add_trace(go.Scatter(
        x=pred, y=real, mode="markers+lines",
        marker=dict(size=[6 + min(c, 80) / 4 for c in counts], color="#1976D2"),
        name="Observed", text=[f"n={c}" for c in counts], hovertemplate="%{text}<br>predicted=%{x:.2f}<br>realized=%{y:.2f}",
    ))
    fig.update_layout(
        title=f"Calibration (Brier score: {brier:.4f}, lower is better)",
        xaxis=dict(title="Predicted probability", range=[0, 1]),
        yaxis=dict(title="Observed frequency", range=[0, 1]),
        height=420, template="plotly_white",
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig, brier


DISCLAIMER = (
    "*Past performance does not guarantee future results. Backtests are subject to "
    "lookahead bias, survivorship bias, and overfitting.*"
)
