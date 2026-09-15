"""Streamlit presentation for the Time--Price Area Predictiveness Lab.

This module contains presentation and orchestration only.  Feature
construction and all statistical work remain in :mod:`area_lab.features` and
:mod:`area_lab.models`; those imports are intentionally lazy so the rest of
SOXL Pro can still load while the research package is unavailable.
"""

from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import math
from typing import Any, Mapping
import uuid

import numpy as np
import pandas as pd
import streamlit as st


INTERPRETATION_TEXT = (
    "This tool tests statistical associations in historical data. It does not "
    "establish causation or guarantee future performance. A relationship is "
    "meaningful only if it remains stable in untouched out-of-sample data and "
    "adds value beyond standard volatility and momentum measures."
)

ANCHOR_MODES = {
    "low20": "Most recent 20-session closing-price low",
    "high20": "Most recent 20-session closing-price high",
    "swing_low": "Most recent confirmed swing low",
    "swing_high": "Most recent confirmed swing high",
    "rolling": "Start of current rolling window",
    "fixed": "Fixed calendar anchor (exploratory only)",
}
LOOKBACKS = (5, 10, 20, 60)
VOL_WINDOWS = (10, 20, 60)
HORIZON_CHOICES = (1, 2, 3, 5, 10, 20, 40, 60)
SPLIT_CHOICES = ("split", "expanding", "rolling", "custom")


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    return str(value)


def _signature(config: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(config), sort_keys=True, default=_json_default, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _normalise_index(index: Any) -> pd.DatetimeIndex:
    parsed = pd.to_datetime(index, errors="coerce")
    if not isinstance(parsed, pd.DatetimeIndex):
        parsed = pd.DatetimeIndex(parsed)
    if parsed.tz is not None:
        parsed = parsed.tz_localize(None)
    return parsed


def _completed_ohlc(price_data: pd.DataFrame | pd.Series | None) -> pd.DataFrame:
    """Return only completed, adjusted OHLC sessions with a naive date index."""
    if price_data is None:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close"])
    if isinstance(price_data, pd.Series):
        raw = price_data.rename("Close").to_frame()
    else:
        raw = price_data.copy()
    if raw.empty or "Close" not in raw.columns:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close"])

    # This is the app's canonical completed-session rule.  It intentionally
    # comes from landing_signal rather than importing app.py.
    from landing_signal import completed_close_history

    completed_close = completed_close_history(raw[["Close"]])
    if completed_close.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close"])
    raw.index = _normalise_index(raw.index)
    raw = raw[~raw.index.isna()]
    raw = raw[~raw.index.duplicated(keep="last")].sort_index()
    keep = _normalise_index(completed_close.index)
    raw = raw.loc[raw.index.isin(keep)]
    columns = [column for column in ("Open", "High", "Low", "Close") if column in raw]
    if "Close" not in columns:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close"])
    # A yfinance adjusted history normally has every OHLC column.  Refuse an
    # incomplete source rather than fabricate missing prices for a study.
    if not {"Open", "High", "Low", "Close"}.issubset(raw.columns):
        return pd.DataFrame(columns=["Open", "High", "Low", "Close"])
    raw = raw[["Open", "High", "Low", "Close"]].apply(
        pd.to_numeric, errors="coerce"
    )
    raw = raw.dropna(subset=["Open", "High", "Low", "Close"])
    return raw[(raw > 0).all(axis=1)].copy()


@st.cache_data(show_spinner=False, ttl=3600)
def _fetch_soxl_history() -> pd.DataFrame:
    """Fetch adjusted SOXL history lazily and remove the incomplete session."""
    import yfinance as yf

    raw = yf.Ticker("SOXL").history(period="max", auto_adjust=True)
    return _completed_ohlc(raw)


def _parse_optional_iso(value: str, label: str) -> str | None:
    value = str(value or "").strip()
    if not value:
        return None
    try:
        parsed = pd.to_datetime(value, format="%Y-%m-%d", errors="raise")
        return None if pd.isna(parsed) else parsed.date().isoformat()
    except (TypeError, ValueError):
        return None


def _date_text(label: str, key: str) -> str | None:
    return _parse_optional_iso(st.text_input(label, value="", key=key), label)


def _custom_boundaries_are_meaningful(config: Mapping[str, Any]) -> bool:
    """Require an ordered, non-empty custom train/validation/test boundary."""
    required = ("train_start", "train_end", "validation_end", "test_start")
    if any(config.get(key) is None for key in required):
        return False
    try:
        train_start = pd.Timestamp(config["train_start"])
        train_end = pd.Timestamp(config["train_end"])
        validation_end = pd.Timestamp(config["validation_end"])
        test_start = pd.Timestamp(config["test_start"])
        test_end = (
            pd.Timestamp(config["test_end"])
            if config.get("test_end") is not None
            else None
        )
    except (TypeError, ValueError):
        return False
    if not (train_start < train_end < validation_end <= test_start):
        return False
    return test_end is None or test_end >= test_start


def _render_controls() -> dict[str, Any]:
    """Render every analysis control and return a model-ready config."""
    st.markdown("#### Study configuration")
    left, right = st.columns(2)
    with left:
        anchor_mode = st.selectbox(
            "Anchor rule",
            list(ANCHOR_MODES),
            format_func=lambda value: ANCHOR_MODES[value],
            index=0,
            key="area_lab_anchor_mode",
        )
        lookback = st.selectbox(
            "Rolling lookback sessions (rolling anchors only)",
            LOOKBACKS,
            index=2,
            disabled=anchor_mode != "rolling",
            help=(
                "Low/high rules always use their fixed trailing 20 closes. "
                "The lookback control applies only to the rolling-start rule."
            ),
            key="area_lab_lookback",
        )
        if anchor_mode != "rolling":
            # Keep the submitted config honest even if a prior rerun had a
            # different rolling selection in the disabled widget.
            lookback = 20
        pivot_bars = st.number_input(
            "Confirmed swing pivot bars",
            min_value=1,
            max_value=20,
            value=3,
            step=1,
            key="area_lab_pivot_bars",
            help="A swing is available only after this many subsequent sessions.",
        )
        vol_window = st.selectbox(
            "Trailing volatility window",
            VOL_WINDOWS,
            index=1,
            key="area_lab_vol_window",
        )
        normalization = st.radio(
            "Primary normalization",
            ["volatility", "none"],
            index=0,
            format_func=lambda value: (
                "Volatility-normalized area" if value == "volatility" else "None (log-area sensitivity)"
            ),
            key="area_lab_normalization",
        )
        fixed_anchor = ""
        if anchor_mode == "fixed":
            fixed_anchor = st.text_input(
                "Fixed anchor date (ISO, exploratory only)",
                value="",
                key="area_lab_fixed_anchor",
            )
    with right:
        horizons = st.multiselect(
            "Forward horizons (trading sessions)",
            HORIZON_CHOICES,
            default=[1, 5, 10, 20],
            key="area_lab_horizons",
        )
        quantiles = st.radio(
            "Area quantile buckets",
            [5, 10],
            index=0,
            format_func=lambda value: f"{value} equal-sized buckets",
            key="area_lab_quantiles",
        )
        large_percentile = st.selectbox(
            "Large future-area percentile",
            [75, 80, 90, 95],
            index=2,
            format_func=lambda value: f"{value}th percentile",
            key="area_lab_large_percentile",
        )
        abs_threshold_pct = st.number_input(
            "Large absolute-return threshold (%)",
            min_value=0.0,
            max_value=100.0,
            value=5.0,
            step=0.5,
            key="area_lab_abs_return_threshold",
        )
        validation_mode = st.selectbox(
            "Validation mode",
            SPLIT_CHOICES,
            format_func=lambda value: {
                "split": "Chronological 70 / 15 / 15 split",
                "expanding": "Expanding walk-forward",
                "rolling": "Rolling walk-forward",
                "custom": "User-defined date split",
            }[value],
            key="area_lab_validation_mode",
        )
        economic_min = st.number_input(
            "Economic minimum improvement (relative RMSE %)",
            min_value=0.0,
            max_value=100.0,
            value=2.0,
            step=0.5,
            key="area_lab_economic_min_improvement",
            help="Used only as a relative-RMSE relevance threshold; this is not a profit estimate.",
        )

    st.markdown("##### Date range and walk-forward settings")
    split_left, split_mid, split_right = st.columns(3)
    with split_left:
        train_fraction = st.number_input(
            "Train share",
            min_value=0.05,
            max_value=0.90,
            value=0.70,
            step=0.05,
            key="area_lab_train_fraction",
        )
    with split_mid:
        validation_fraction = st.number_input(
            "Validation share",
            min_value=0.05,
            max_value=0.50,
            value=0.15,
            step=0.05,
            key="area_lab_validation_fraction",
        )
    with split_right:
        test_fraction = st.number_input(
            "Final test share",
            min_value=0.05,
            max_value=0.50,
            value=0.15,
            step=0.05,
            key="area_lab_test_fraction",
        )
    fractions_valid = (
        all(
            np.isfinite(float(value)) and float(value) > 0
            for value in (train_fraction, validation_fraction, test_fraction)
        )
        and math.isclose(
            float(train_fraction)
            + float(validation_fraction)
            + float(test_fraction),
            1.0,
            abs_tol=1e-6,
        )
    )
    if not fractions_valid:
        st.warning("Train, validation, and final-test shares must add to 100%.")

    date_left, date_right = st.columns(2)
    with date_left:
        train_start = _date_text("Train start (ISO, optional)", "area_lab_train_start")
        train_end = _date_text("Train end (ISO, optional)", "area_lab_train_end")
        validation_end = _date_text(
            "Validation end (ISO, optional)", "area_lab_validation_end"
        )
    with date_right:
        test_start = _date_text("Test start (ISO, optional)", "area_lab_test_start")
        test_end = _date_text("Test end (ISO, optional)", "area_lab_test_end")
        rolling_train_sessions = st.number_input(
            "Rolling training sessions",
            min_value=20,
            max_value=5000,
            value=756,
            step=1,
            key="area_lab_rolling_train_sessions",
        )
        retrain_sessions = st.number_input(
            "Retrain every sessions",
            min_value=1,
            max_value=1000,
            value=63,
            step=1,
            key="area_lab_retrain_sessions",
        )

    if not horizons:
        st.warning("Select at least one forward horizon before analyzing.")
    if anchor_mode == "rolling":
        st.caption(
            "Rolling anchor definition: the anchor is the start of a lookback "
            "window starting at t-N+1, using N closes and N-1 elapsed "
            "trading-session intervals. This differs from the fixed trailing "
            "20-close low/high rules."
        )
    elif anchor_mode in {"low20", "high20"}:
        st.caption(
            "This anchor rule always uses its fixed trailing 20 completed closes; "
            "the disabled lookback control applies only to rolling anchors."
        )
    if anchor_mode == "fixed":
        st.warning(
            "Fixed anchors are exploratory only and cannot establish cross-anchor robustness."
        )

    config = {
        "anchor_mode": anchor_mode,
        "lookback": int(lookback),
        "pivot_bars": int(pivot_bars),
        "vol_window": int(vol_window),
        "fixed_anchor": _parse_optional_iso(fixed_anchor, "Fixed anchor date"),
        "normalization": normalization,
        "horizons": [int(value) for value in horizons],
        "quantiles": int(quantiles),
        "large_percentile": int(large_percentile),
        "abs_return_threshold": float(abs_threshold_pct) / 100.0,
        "validation_mode": validation_mode,
        "train_start": train_start,
        "train_end": train_end,
        "validation_end": validation_end,
        "test_start": test_start,
        "test_end": test_end,
        "rolling_train_sessions": int(rolling_train_sessions),
        "retrain_sessions": int(retrain_sessions),
        "economic_min_improvement": float(economic_min) / 100.0,
        "train_fraction": float(train_fraction),
        "validation_fraction": float(validation_fraction),
        "test_fraction": float(test_fraction),
    }
    invalid_dates = [
        label for key, label in (
            ("area_lab_train_start", "Train start"),
            ("area_lab_train_end", "Train end"),
            ("area_lab_validation_end", "Validation end"),
            ("area_lab_test_start", "Test start"),
            ("area_lab_test_end", "Test end"),
        )
        if str(st.session_state.get(key, "")).strip()
        and _parse_optional_iso(st.session_state[key], label) is None
    ]
    config["_invalid_dates"] = invalid_dates
    for label in invalid_dates:
        st.error(f"{label} must be a valid YYYY-MM-DD date. Correct it before analyzing.")
    if validation_mode == "custom" and not _custom_boundaries_are_meaningful(config):
        st.warning(
            "Custom validation requires ordered, meaningful train/validation/test "
            "date boundaries. Invalid or blank optional dates are ignored; enter "
            "train start/end, validation end, and test start to enable analysis."
        )
    return config


def _feature_rows(features: pd.DataFrame) -> pd.DataFrame:
    frame = features.copy()
    if frame.empty:
        return frame
    frame.index = _normalise_index(frame.index)
    frame = frame.loc[~frame.index.isna()].sort_index()
    return frame


def _render_area_chart(ohlc: pd.DataFrame, features: pd.DataFrame) -> None:
    """Render an actual-price chart and data-unit anchor rectangle."""
    if ohlc.empty or features.empty:
        return
    try:
        import plotly.graph_objects as go
    except ImportError:
        st.warning("Plotly is unavailable, so the illustrative area chart is hidden.")
        return

    frame = _feature_rows(features)
    eligible = frame["close"].dropna() if "close" in frame else pd.Series(dtype=float)
    if eligible.empty:
        st.info("No feature rows with a current close are available for chart selection.")
        return
    options = [pd.Timestamp(value).date().isoformat() for value in eligible.index]
    selected = st.selectbox(
        "Research display date (chart selection is illustrative only)",
        options,
        index=len(options) - 1,
        key="area_lab_selected_date",
    )
    selected_ts = pd.Timestamp(selected)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=ohlc.index,
            y=ohlc["Close"],
            mode="lines",
            name="Adjusted close",
            line={"color": "#2563eb", "width": 1.5},
        )
    )
    row = frame.loc[frame.index == selected_ts]
    if row.empty:
        row = frame.iloc[[-1]]
    observation = row.iloc[-1]
    anchor_date = pd.to_datetime(observation.get("anchor_date"), errors="coerce")
    anchor_price = pd.to_numeric(observation.get("anchor_price"), errors="coerce")
    current_price = pd.to_numeric(observation.get("close"), errors="coerce")
    current_date = row.index[-1]
    if pd.notna(anchor_date) and pd.notna(anchor_price) and pd.notna(current_price):
        lower, upper = sorted([float(anchor_price), float(current_price)])
        fig.add_vline(x=anchor_date, line_dash="dot", line_color="#f97316")
        fig.add_vline(x=current_date, line_dash="dot", line_color="#16a34a")
        fig.add_hline(y=float(anchor_price), line_dash="dot", line_color="#f97316")
        fig.add_shape(
            type="rect",
            x0=anchor_date,
            x1=current_date,
            y0=lower,
            y1=upper,
            fillcolor="rgba(249,115,22,0.14)",
            line={"color": "#f97316", "width": 1},
        )
        fig.add_trace(
            go.Scatter(
                x=[anchor_date, current_date],
                y=[float(anchor_price), float(current_price)],
                mode="markers",
                name="Anchor / evaluation",
                marker={"size": 8, "color": ["#f97316", "#16a34a"]},
                hovertemplate="%{x|%Y-%m-%d}<br>$%{y:.4f}<extra></extra>",
            )
        )
    fig.update_layout(
        title="Adjusted SOXL close and data-unit time–price rectangle",
        height=420,
        template="plotly_white",
        xaxis_title="Completed trading date",
        yaxis_title="Adjusted price",
        showlegend=True,
    )
    try:
        event = st.plotly_chart(
            fig,
            use_container_width=True,
            key="area_lab_price_chart",
            on_select="rerun",
            selection_mode=("points",),
        )
        # A date selector remains the durable fallback when a browser does not
        # send a Plotly selection event through Streamlit's rerun.
        points = getattr(getattr(event, "selection", None), "points", None)
        if points is None and isinstance(event, Mapping):
            points = event.get("selection", {}).get("points", [])
        if points:
            point_date = pd.to_datetime(points[0].get("x"), errors="coerce")
            if pd.notna(point_date):
                st.caption(
                    f"Selected chart point: {pd.Timestamp(point_date).date().isoformat()}. "
                    "Use the date selector above for a stable audit selection."
                )
    except TypeError:
        # Streamlit versions before Plotly selection support still get the
        # complete visual panel and date selector.
        st.plotly_chart(fig, use_container_width=True, key="area_lab_price_chart")

    values = {
        "raw area": observation.get("area_raw"),
        "log area": observation.get("area_log"),
        "signed area": observation.get("area_signed"),
        "normalized area": observation.get("area_norm"),
        "elapsed trading sessions": observation.get("elapsed_sessions"),
        "anchor date": observation.get("anchor_date"),
        "anchor price": observation.get("anchor_price"),
        "anchor confirmation date": observation.get("anchor_confirmation_date"),
        "current price": observation.get("close"),
    }
    st.markdown("**Selected observation (actual data units)**")
    st.dataframe(pd.DataFrame([values]), hide_index=True, width="stretch")
    st.caption(
        "The rectangle is illustrative. Research calculations use trading-session "
        "counts and adjusted prices, never screen pixels."
    )
    st.caption(
        "Target labels use each future date's own causal anchor. Anchors can reset "
        "between t and t+h, so mathematical persistence of shared geometry must "
        "not be misread as a novel forecast edge."
    )


def _frame(value: Any) -> pd.DataFrame:
    return value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _values(frame: pd.DataFrame, column: str) -> list[Any]:
    if column not in frame or frame.empty:
        return []
    values = frame[column].dropna().tolist()
    return list(dict.fromkeys(values))


def _choose_value(values: list[Any], preferred: Any, fallback: Any = None) -> Any:
    if not values:
        return fallback
    for value in values:
        if str(value).lower() == str(preferred).lower():
            return value
    return values[0]


def _filter_result(
    frame: pd.DataFrame,
    horizon: Any = None,
    split: Any = None,
    model: Any = None,
) -> pd.DataFrame:
    frame = _frame(frame)
    if frame.empty:
        return frame
    if horizon is not None and "horizon" in frame:
        numeric = pd.to_numeric(frame["horizon"], errors="coerce")
        frame = frame.loc[numeric == float(horizon)]
    if split is not None and "split" in frame:
        frame = frame.loc[frame["split"].astype(str) == str(split)]
    if model is not None and "model" in frame:
        frame = frame.loc[frame["model"].astype(str) == str(model)]
    return frame


def _chart_or_info(frame: pd.DataFrame, chart_kind: str) -> None:
    if frame.empty:
        st.info("No observations are available for this selection.")
        return
    try:
        import plotly.express as px

        if chart_kind == "bucket":
            y = "mean_future_area"
            if y in frame:
                st.plotly_chart(
                    px.bar(frame, x="bucket", y=y, title="Mean future normalized area by current-area bucket"),
                    use_container_width=True,
                )
        elif chart_kind == "scatter":
            # The research question is current area versus the future realized
            # area.  A model forecast scatter is a different diagnostic and is
            # only retained as a compatibility fallback for older result
            # frames that predate the current_area prediction column.
            if {"current_area", "actual_area"}.issubset(frame.columns):
                x, y = "current_area", "actual_area"
                title = "Current normalized area versus future realized area"
            else:
                x = "actual_area" if "actual_area" in frame else None
                y = "predicted_area" if "predicted_area" in frame else None
                title = "Realized versus predicted future area (legacy diagnostic)"
            if x and y:
                st.plotly_chart(
                    px.scatter(frame, x=x, y=y, title=title),
                    use_container_width=True,
                )
        elif chart_kind == "calibration":
            if {"predicted_probability", "observed_frequency"}.issubset(frame.columns):
                fig = px.line(
                    frame,
                    x="predicted_probability",
                    y="observed_frequency",
                    color="model" if "model" in frame else None,
                    markers=True,
                    title="Final calibration",
                )
                st.plotly_chart(fig, use_container_width=True)
    except (ImportError, ValueError):
        st.info("Chart data is available in the table below.")


def _download_frame(
    label: str, frame: pd.DataFrame, filename: str, key: str, index: bool = False
) -> None:
    st.download_button(
        label,
        data=frame.to_csv(index=index),
        file_name=filename,
        mime="text/csv",
        key=key,
    )


def _render_downloads(result: Mapping[str, Any], config: Mapping[str, Any]) -> None:
    st.markdown("#### Download complete research outputs")
    data_features = _frame(result.get("features", result.get("data_features")))
    labels = _frame(result.get("labels", result.get("data_labels")))
    outputs = [
        ("Download features (CSV)", data_features, "area_lab_features.csv", "features"),
        ("Download labels (CSV)", labels, "area_lab_labels.csv", "labels"),
        ("Download comparisons (CSV)", _frame(result.get("comparison")), "area_lab_comparison.csv", "comparison"),
        ("Download regression (CSV)", _frame(result.get("regression")), "area_lab_regression.csv", "regression"),
        ("Download buckets (CSV)", _frame(result.get("buckets")), "area_lab_buckets.csv", "buckets"),
        ("Download calibration (CSV)", _frame(result.get("calibration")), "area_lab_calibration.csv", "calibration"),
        ("Download confusion metrics (CSV)", _frame(result.get("confusion")), "area_lab_confusion.csv", "confusion"),
        ("Download split audit (CSV)", _frame(result.get("splits")), "area_lab_splits.csv", "splits"),
    ]
    columns = st.columns(2)
    for index, (label, frame, filename, key) in enumerate(outputs):
        with columns[index % 2]:
            _download_frame(label, frame, filename, f"area_lab_download_{key}")
    st.download_button(
        "Download analysis configuration (JSON)",
        data=json.dumps(dict(config), indent=2, default=_json_default),
        file_name="area_lab_config.json",
        mime="application/json",
        key="area_lab_download_config",
    )


def _render_results(result: Mapping[str, Any], config: Mapping[str, Any]) -> None:
    """Render result frames without triggering a new analysis."""
    verdict = str(result.get("verdict") or "Insufficient evidence")
    detail = str(result.get("verdict_detail") or "No verdict detail was returned.")
    st.subheader("Summary verdict — final out-of-sample evidence")
    st.info(f"**{verdict}**\n\n{detail}")
    st.warning(INTERPRETATION_TEXT)
    st.caption(
        "No forecasts or buy/sell signals are generated. Economic relevance is "
        "reported as relative prediction error, not a profit claim."
    )
    metadata = result.get("metadata")
    if isinstance(metadata, Mapping):
        with st.expander("Run provenance and reconstruction metadata", expanded=True):
            provenance = {
                "config hash (immutable run)": metadata.get("config_hash")
                or _signature(config),
                "source": metadata.get("source")
                or "Completed adjusted OHLC supplied to the study",
                "source start": metadata.get("source_start"),
                "source end": metadata.get("source_end"),
                "source rows": metadata.get("source_rows"),
                "adjusted prices": metadata.get("adjusted_prices", True),
                "completed sessions only": metadata.get("completed_sessions_only", True),
                "reconstruction": metadata.get("reconstruction")
                or "Causal rule-based anchor reconstruction",
            }
            st.table(pd.DataFrame([provenance]))
            st.caption(
                "The run hash identifies the exact controls used for these "
                "results; changing controls requires a new analysis."
            )

    warnings = result.get("warnings", [])
    if warnings:
        with st.expander("Data-quality and leakage warnings", expanded=True):
            for warning in warnings:
                st.warning(str(warning))

    comparison = _frame(result.get("comparison"))
    regression = _frame(result.get("regression"))
    buckets = _frame(result.get("buckets"))
    predictions = _frame(result.get("predictions"))
    calibration = _frame(result.get("calibration"))
    coefficients = _frame(result.get("coefficients"))
    confusion = _frame(result.get("confusion"))
    splits = _frame(result.get("splits"))
    stability = _frame(result.get("stability"))
    inference = _frame(result.get("inference"))

    horizon_values = sorted(
        [value for value in _values(comparison, "horizon")],
        key=lambda value: float(value) if str(value).replace(".", "", 1).isdigit() else str(value),
    )
    if not horizon_values:
        horizon_values = sorted(_values(regression, "horizon"), key=str)
    if not horizon_values:
        horizon_values = list(config.get("horizons", []))
    split_values = _values(comparison, "split") or _values(regression, "split")
    model_values = _values(comparison, "model")
    preferred_split = _choose_value(
        split_values, "test", _choose_value(split_values, "final_test", None)
    )
    # Keep final-test evidence as the default, while permitting any exact label
    # supplied by a model implementation (e.g. "final").
    if split_values:
        final_candidates = [
            value
            for value in split_values
            if any(token in str(value).lower() for token in ("test", "final"))
        ]
        preferred_split = final_candidates[-1] if final_candidates else preferred_split

    st.markdown("#### Display filters (do not rerun analysis)")
    filter_cols = st.columns(3)
    with filter_cols[0]:
        display_horizon = st.selectbox(
            "Display horizon",
            horizon_values or ["No horizon"],
            key="area_lab_display_horizon",
        )
    with filter_cols[1]:
        display_split = st.selectbox(
            "Display split",
            split_values or ["No split"],
            index=(split_values.index(preferred_split) if preferred_split in split_values else 0),
            key="area_lab_display_split",
        )
    with filter_cols[2]:
        display_model = st.selectbox(
            "Display model",
            model_values or ["All models"],
            key="area_lab_display_model",
        )
    h_filter = None if display_horizon == "No horizon" else display_horizon
    s_filter = None if display_split == "No split" else display_split
    m_filter = None if display_model == "All models" else display_model

    st.markdown("#### Split-date audit")
    split_view = _filter_result(splits, horizon=h_filter, split=s_filter)
    if split_view.empty:
        split_view = _filter_result(splits, horizon=h_filter)
    if split_view.empty:
        st.info("No split audit rows were returned.")
    else:
        st.dataframe(split_view, hide_index=True, width="stretch")

    st.markdown("#### Training-fit regression diagnostics")
    st.caption(
        "These coefficients and inferential fields describe the fold's "
        "training fit. They are not refits on, or inference from, the held-out "
        "validation/final-test rows; compare held-out predictions below for "
        "out-of-sample evidence. Fold, fit-cutoff, training-start, and "
        "training-end columns are shown when returned by the model."
    )
    regression_view = _filter_result(regression, horizon=h_filter, split=s_filter)
    st.dataframe(regression_view, hide_index=True, width="stretch")

    st.markdown("#### Quantile/bucket analysis")
    bucket_view = _filter_result(buckets, horizon=h_filter, split=s_filter)
    st.dataframe(bucket_view, hide_index=True, width="stretch")
    _chart_or_info(bucket_view, "bucket")

    st.markdown("#### Benchmark comparison")
    comparison_view = _filter_result(
        comparison, horizon=h_filter, split=s_filter, model=m_filter
    )
    # Show all models when the user selects the all-model fallback.
    if comparison_view.empty and m_filter is not None:
        comparison_view = _filter_result(comparison, horizon=h_filter, split=s_filter)
    st.dataframe(comparison_view, hide_index=True, width="stretch")

    st.markdown("#### Final predictions and area scatter")
    prediction_view = _filter_result(
        predictions, horizon=h_filter, split=s_filter, model=m_filter
    )
    if prediction_view.empty and s_filter is not None:
        final_predictions = _filter_result(predictions, horizon=h_filter, model=m_filter)
        if not final_predictions.empty:
            prediction_view = final_predictions
    _chart_or_info(prediction_view, "scatter")
    st.dataframe(prediction_view, hide_index=True, width="stretch")

    st.markdown("#### Coefficients / standardized feature display")
    coefficient_view = _filter_result(
        coefficients, horizon=h_filter, split=s_filter, model=m_filter
    )
    st.dataframe(coefficient_view, hide_index=True, width="stretch")

    st.markdown("#### Classification calibration and confusion metrics")
    calibration_view = _filter_result(
        calibration, horizon=h_filter, split=s_filter, model=m_filter
    )
    st.dataframe(calibration_view, hide_index=True, width="stretch")
    _chart_or_info(calibration_view, "calibration")
    confusion_view = _filter_result(
        confusion, horizon=h_filter, split=s_filter, model=m_filter
    )
    st.dataframe(confusion_view, hide_index=True, width="stretch")

    if not inference.empty or not stability.empty:
        with st.expander("Dependence-aware inference and stability"):
            if not inference.empty:
                st.dataframe(inference, hide_index=True, width="stretch")
            if not stability.empty:
                st.dataframe(stability, hide_index=True, width="stretch")

    features = _frame(result.get("features", result.get("data_features")))
    if not features.empty:
        with st.expander("Normalized area time series and complete history ledger"):
            try:
                import plotly.express as px

                chart_features = features.copy()
                chart_features.index = _normalise_index(chart_features.index)
                series_cols = [
                    column
                    for column in ("area_norm", "area_log", "area_signed")
                    if column in chart_features
                ]
                if series_cols:
                    st.plotly_chart(
                        px.line(
                            chart_features.reset_index(),
                            x=chart_features.index.name or "index",
                            y=series_cols,
                            title="Causal current area variables",
                        ),
                        use_container_width=True,
                    )
            except (ImportError, ValueError):
                pass
            ledger_columns = [
                column
                for column in (
                    "close",
                    "anchor_date",
                    "anchor_price",
                    "anchor_type",
                    "anchor_confirmation_date",
                    "elapsed_sessions",
                    "area_raw",
                    "area_log",
                    "area_signed",
                    "area_norm",
                )
                if column in features
            ]
            st.dataframe(features[ledger_columns], width="stretch")

    _render_downloads(result, config)


def _render_pending(job_id: str) -> bool:
    """Render cancellable status; return whether the caller should stop."""
    from . import jobs

    snapshot = jobs.get_job(job_id)
    if snapshot is None:
        st.error("The analysis worker is no longer available. Please run it again.")
        return False
    status = snapshot["status"]
    if status in {"queued", "running"}:
        st.progress(float(snapshot.get("fraction", 0.0)))
        st.caption(str(snapshot.get("message", "Analysis running")))
        if st.button("Cancel analysis", key="area_lab_cancel_analysis"):
            jobs.cancel_job(job_id)
            st.info("Cancellation requested; waiting for the worker to stop safely.")
        # Fragment polling is used when available; the ordinary status still
        # renders in older Streamlit versions and in AppTest.
        fragment = getattr(st, "fragment", None)
        if fragment is not None:
            @fragment(run_every="1s")
            def _poll_area_lab_job():
                current = jobs.get_job(job_id)
                if current and current["status"] in {"queued", "running"}:
                    st.progress(float(current.get("fraction", 0.0)))
                    st.caption(str(current.get("message", "Analysis running")))
                elif current and current["status"] == "completed":
                    st.session_state["area_lab_result"] = current["result"]
                    st.rerun(scope="app")
                elif current and current["status"] in {"cancelled", "error"}:
                    st.rerun(scope="app")

            _poll_area_lab_job()
        return True
    if status == "cancelled":
        st.info("Analysis cancelled. No partial result was presented as evidence.")
        return False
    if status == "error":
        st.error(f"Analysis failed: {snapshot.get('error') or snapshot.get('message')}")
        return False
    if status == "completed" and snapshot.get("result") is not None:
        st.session_state["area_lab_result"] = snapshot["result"]
        return False
    return False


def render_area_lab(
    price_data: pd.DataFrame | pd.Series | None = None,
    history: pd.DataFrame | pd.Series | None = None,
) -> None:
    """Render the dedicated Time--Price Area Predictiveness Lab panel.

    ``price_data`` is an optional integration seam for the host app and unit
    tests.  When omitted, adjusted SOXL history is fetched lazily from
    yfinance.  The date selector/chart is for inspection only: automatic
    anchors in the feature pipeline always drive the backtest.
    """
    st.header("Time–Price Area Predictiveness Lab")
    enabled = st.checkbox(
        "Enable Time–Price Area Research",
        value=False,
        key="area_lab_enabled",
    )
    st.caption(
        "Research uses completed adjusted SOXL sessions and reproducible rule-based "
        "anchors. It does not produce forecasts or trading signals."
    )
    if not enabled:
        active_id = st.session_state.get("area_lab_job_id")
        if active_id:
            from . import jobs
            snapshot = jobs.get_job(active_id)
            if snapshot and snapshot["status"] in {"queued", "running"}:
                jobs.cancel_job(active_id)
                st.info("Research disabled. Cancellation has been requested for the running analysis.")
        return

    config = _render_controls()
    st.warning(
        "Target-label caveat: every future date uses its own causal anchor, and "
        "that anchor may reset. Shared time–price geometry can therefore create "
        "mathematical persistence; it must not be interpreted as a novel forecast edge."
    )
    source = price_data if price_data is not None else history
    if source is None:
        try:
            source = _fetch_soxl_history()
        except Exception as exc:
            st.error(f"Unable to load completed adjusted SOXL history: {exc}")
            return
    ohlc = _completed_ohlc(source)
    if ohlc.empty:
        st.error(
            "No complete adjusted OHLC history is available. The study will not "
            "fabricate missing prices."
        )
        return

    try:
        from .features import build_features

        preview_features = build_features(ohlc, config)
    except Exception as exc:
        st.error(f"Unable to build causal area features: {type(exc).__name__}: {exc}")
        return
    preview_features = _feature_rows(preview_features)
    _render_area_chart(ohlc, preview_features)

    from . import jobs

    # Streamlit's session_state object is a global proxy, so its ``id`` is not
    # a user/session identity.  Generate a UUID once in the actual per-session
    # state instead; this prevents duplicate-job/result mix-ups across users.
    session_id = st.session_state.setdefault("area_lab_session_id", uuid.uuid4().hex)
    current_signature = _signature(config)
    custom_dates_valid = (
        config.get("validation_mode") != "custom"
        or _custom_boundaries_are_meaningful(config)
    )
    shares = tuple(
        float(config.get(key, 0.0))
        for key in ("train_fraction", "validation_fraction", "test_fraction")
    )
    fractions_valid = all(np.isfinite(value) and value > 0 for value in shares) and math.isclose(
        sum(shares), 1.0, abs_tol=1e-6
    )
    fixed_anchor_valid = (
        config.get("anchor_mode") != "fixed"
        or bool(config.get("fixed_anchor"))
    )
    if not fixed_anchor_valid:
        st.warning(
            "A valid fixed anchor date is required for the exploratory fixed "
            "anchor rule; the date was blank or invalid."
        )
    active_job_id = st.session_state.get("area_lab_job_id")
    active_snapshot = jobs.get_job(active_job_id)
    if active_snapshot and active_snapshot["status"] in {"queued", "running"}:
        st.warning("An analysis is already running. Change controls after it finishes or cancel it.")
        _render_pending(active_job_id)
        return
    if (
        active_snapshot
        and active_snapshot["status"] == "completed"
        and active_snapshot.get("result") is not None
    ):
        # A worker may finish between two Streamlit reruns.  Capture its
        # immutable result before rendering controls/results, rather than
        # falling through to the "begin" message.
        st.session_state["area_lab_result"] = active_snapshot["result"]
        # The complete frames are now owned by session_state.  Release the
        # duplicate registry reference for this session so repeated reruns do
        # not retain large historical result frames indefinitely.
        jobs.clear_finished_jobs(session_id=session_id)

    result_metadata = (
        st.session_state.get("area_lab_result", {}).get("metadata", {})
        if isinstance(st.session_state.get("area_lab_result"), Mapping)
        else {}
    )
    old_signature = (
        st.session_state.get("area_lab_config_signature")
        or result_metadata.get("config_hash")
    )
    if (
        st.session_state.get("area_lab_result") is not None
        and old_signature
        and old_signature != current_signature
    ):
        st.warning(
            "Controls differ from the completed analysis. The displayed results and "
            "downloads are labeled with the previous run; Analyze Historical "
            "Predictiveness to refresh them."
        )

    run = st.button(
        "Analyze Historical Predictiveness",
        key="area_lab_analyze",
        disabled=(
            not bool(config.get("horizons"))
            or not custom_dates_valid
            or not fractions_valid
            or not fixed_anchor_valid
            or bool(config.get("_invalid_dates"))
        ),
    )
    if run:
        job_id = jobs.start_analysis_job(ohlc, config, session_id=session_id)
        st.session_state["area_lab_job_id"] = job_id
        st.session_state["area_lab_config"] = dict(config)
        st.session_state["area_lab_config_signature"] = current_signature
        st.session_state["area_lab_result"] = None
        st.rerun()
        return

    result = st.session_state.get("area_lab_result")
    if result is not None:
        result_config = st.session_state.get(
            "area_lab_config",
            result.get("config", config) if isinstance(result, Mapping) else config,
        )
        _render_results(result, result_config)
    elif active_snapshot and active_snapshot["status"] not in {"completed"}:
        _render_pending(active_job_id)
    else:
        st.info("Configure the study and select Analyze Historical Predictiveness to begin.")
