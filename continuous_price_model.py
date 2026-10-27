"""Continuous conditional return model, separate from historical analogue studies."""
import numpy as np
import pandas as pd
from scipy.stats import t


def prepare_history(closes):
    values = pd.to_numeric(pd.Series(closes), errors="coerce")
    values = values[np.isfinite(values) & (values > 0)].sort_index()
    values = values[~values.index.duplicated(keep="last")]
    frame = pd.DataFrame({"close": values})
    frame["anchor"] = np.log(values).rolling(252).mean()
    frame["relative"] = np.log(values) - frame["anchor"]
    return frame


def fit_model(prepared, horizon):
    if horizon not in (21, 126, 252):
        raise ValueError("Choose one, six, or twelve months.")
    forward = np.log(prepared.close.shift(-horizon) / prepared.close)
    positions = np.arange(251, max(251, len(prepared) - horizon), horizon)
    x = prepared.relative.iloc[positions].to_numpy()
    y = forward.iloc[positions].to_numpy()
    valid = np.isfinite(x) & np.isfinite(y)
    x, y = x[valid], y[valid]
    if len(x) < 8 or np.std(x) < 1e-8:
        raise ValueError("The model needs at least eight completed training periods with varied prices.")
    design = np.column_stack([np.ones(len(x)), x])
    inv = np.linalg.inv(design.T @ design)
    coefficients = inv @ design.T @ y
    df = len(x) - 2
    variance = float(np.sum((y - design @ coefficients)**2) / df)
    if variance <= 1e-12:
        raise ValueError("History has too little return variation to estimate uncertainty.")
    return dict(coefficients=coefficients, inv=inv, variance=variance, df=df,
                count=len(x), anchor=float(prepared.anchor.iloc[-1]),
                xmin=float(x.min()), xmax=float(x.max()),
                history_date=str(pd.Timestamp(prepared.index[-1]).date()))


def predict(model, prices):
    prices = np.asarray(prices, dtype=float)
    x = np.log(prices) - model["anchor"]
    design = np.column_stack([np.ones(len(prices)), x])
    mu = design @ model["coefficients"]
    leverage = np.einsum("ij,jk,ik->i", design, model["inv"], design)
    scale = np.sqrt(model["variance"] * (1 + leverage))
    probability = t.cdf(mu / scale, model["df"])
    return mu, scale, probability, leverage, (x < model["xmin"]) | (x > model["xmax"])


def probability_curve(prepared, horizon):
    model = fit_model(prepared, horizon)
    prices = np.append(np.arange(1, 500, .5), 500)
    _, _, probabilities, _, extrapolated = predict(model, prices)
    return model["count"], [
        dict(price=float(p), probability=float(q), extrapolated=bool(e))
        for p, q, e in zip(prices, probabilities, extrapolated)
    ]


def estimate(prepared, selected_price, horizon):
    if not np.isfinite(selected_price) or not 1 <= selected_price <= 500:
        raise ValueError("Choose a starting price between $1 and $500.")
    model = fit_model(prepared, horizon)
    mu, scale, probability, leverage, extra = predict(model, [selected_price])
    mu, scale, p = float(mu[0]), float(scale[0]), float(probability[0])
    df = model["df"]
    low, high = np.expm1(mu + scale * t.ppf([.1, .9], df))
    # Conditional median in the positive half of the modeled return distribution.
    upside = np.expm1(mu + scale * t.ppf(1 - p/2, df))
    parameter_error = t.ppf(.975, df) * np.sqrt(model["variance"] * leverage[0])
    ci = t.cdf((mu + np.array([-1, 1]) * parameter_error) / scale, df)
    return dict(supported=True, reason="", count=model["count"], score=np.nan,
                probability=p, median_return=float(np.expm1(mu)),
                low_return=float(low), high_return=float(high), upside_return=float(upside),
                ci_low=float(ci[0]), ci_high=float(ci[1]), extrapolated=bool(extra[0]),
                model_label="Continuous relative-price model",
                history_date=model["history_date"])
