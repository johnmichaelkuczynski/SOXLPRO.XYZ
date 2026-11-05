"""Shared long-term rating boundaries and their presentation."""

RATING_THRESHOLDS = {
    "buy_max": 15.0,
    "possible_buy_max": 55.0,
    "possible_sell_min": 65.0,
    "sell_min": 85.0,
}

# Retain the tuple API used by historical reconstruction and comparison exports.
DEFAULT_THRESHOLDS = tuple(RATING_THRESHOLDS.values())
OLD_THRESHOLDS = (15.0, 35.0, 65.0, 85.0)

SIGNAL_COLORS = {
    "STRONG SELL": "#b91c1c",
    "SELL": "#f97316",
    "DO NOTHING": "#64748b",
    "BUY": "#4ade80",
    "STRONG BUY": "#047857",
}

SIGNAL_DISPLAY_LABELS = {
    "STRONG BUY": "BUY",
    "BUY": "POSSIBLE BUY",
    "DO NOTHING": "DO NOTHING",
    "SELL": "POSSIBLE SELL",
    "STRONG SELL": "SELL",
    "INSUFFICIENT HISTORY": "INSUFFICIENT HISTORY",
}


def rating_bands():
    """Generate ordered bar bands from the shared threshold configuration."""
    bounds = (0.0, *RATING_THRESHOLDS.values(), 100.0)
    signals = ("STRONG BUY", "BUY", "DO NOTHING", "SELL", "STRONG SELL")
    inclusivity = ((True, True), (False, True), (False, False),
                   (True, False), (True, True))
    return [
        {
            "signal": signal,
            "label": SIGNAL_DISPLAY_LABELS[signal],
            "color": {
                "DO NOTHING": "#cbd5e1",
                "SELL": "#fb923c",
            }.get(signal, SIGNAL_COLORS[signal]),
            "lower": lower,
            "upper": upper,
            "width": upper - lower,
            "lower_inclusive": inclusive[0],
            "upper_inclusive": inclusive[1],
        }
        for signal, lower, upper, inclusive in zip(
            signals, bounds, bounds[1:], inclusivity
        )
    ]


def rating_threshold_description():
    """Describe the same inclusive/exclusive ranges used by classification."""
    descriptions = []
    for band in rating_bands():
        lower = (
            f"{band['lower']:g}%"
            if band["lower_inclusive"]
            else f"above {band['lower']:g}%"
        )
        upper = (
            f"through {band['upper']:g}% (inclusive)"
            if band["upper_inclusive"]
            else f"to below {band['upper']:g}%"
        )
        descriptions.append(f"{band['label']}: {lower} {upper}")
    return "; ".join(descriptions) + "."
