"""Chronological validation helpers for the time--price area lab.

The functions in this module deliberately operate on row positions after the
input has been sorted by date.  A feature row can only be used for fitting
after its *label end date* has occurred.  This is slightly stricter than
splitting on the observation date alone and prevents an overlapping forward
label from leaking across a fit boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

import numpy as np
import pandas as pd


DEFAULT_HORIZONS = (1, 5, 10, 20)


def _as_date(value: Any) -> pd.Timestamp | None:
    """Return a normalized timestamp, or ``None`` for an empty setting."""

    if value is None or value == "":
        return None
    try:
        result = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(result):
        return None
    return result


def normalize_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Apply documented defaults without changing the caller's dictionary."""

    source = dict(config or {})
    try:
        horizons = [int(h) for h in source.get("horizons", DEFAULT_HORIZONS)]
    except (TypeError, ValueError):
        horizons = list(DEFAULT_HORIZONS)
    horizons = sorted(set(h for h in horizons if h > 0)) or list(DEFAULT_HORIZONS)

    mode = str(source.get("validation_mode", "split")).lower()
    if mode not in {"split", "expanding", "rolling", "custom"}:
        mode = "split"

    anchor_mode = str(source.get("anchor_mode", "low20")).lower()
    allowed_anchor_modes = {
        "low20",
        "high20",
        "swing_low",
        "swing_high",
        "rolling",
        "fixed",
    }
    if anchor_mode not in allowed_anchor_modes:
        anchor_mode = "low20"

    normalization = str(source.get("normalization", "volatility")).lower()
    if normalization not in {"volatility", "none"}:
        normalization = "volatility"

    try:
        lookback = int(source.get("lookback", 20))
    except (TypeError, ValueError):
        lookback = 20
    if lookback not in {5, 10, 20, 60}:
        lookback = 20
    try:
        vol_window = int(source.get("vol_window", 20))
    except (TypeError, ValueError):
        vol_window = 20
    if vol_window not in {10, 20, 60}:
        vol_window = 20

    try:
        pivot_bars = max(1, int(source.get("pivot_bars", 3)))
    except (TypeError, ValueError):
        pivot_bars = 3
    try:
        quantiles = int(source.get("quantiles", 5))
    except (TypeError, ValueError):
        quantiles = 5
    quantiles = 10 if quantiles == 10 else 5
    try:
        large_percentile = float(source.get("large_percentile", 90))
    except (TypeError, ValueError):
        large_percentile = 90.0
    large_percentile = (
        large_percentile if large_percentile in {75.0, 80.0, 90.0, 95.0} else 90.0
    )
    try:
        abs_return_threshold = float(source.get("abs_return_threshold", 0.05))
    except (TypeError, ValueError):
        abs_return_threshold = 0.05
    if not np.isfinite(abs_return_threshold) or abs_return_threshold < 0:
        abs_return_threshold = 0.05
    try:
        rolling_train_sessions = max(
            1, int(source.get("rolling_train_sessions", 756))
        )
    except (TypeError, ValueError):
        rolling_train_sessions = 756
    try:
        retrain_sessions = max(1, int(source.get("retrain_sessions", 63)))
    except (TypeError, ValueError):
        retrain_sessions = 63
    try:
        # At least one validation and one final-test walk-forward block are
        # needed to preserve their separate reporting provenance.
        max_folds = max(2, int(source.get("max_folds", 40)))
    except (TypeError, ValueError):
        max_folds = 40
    try:
        economic_min_improvement = float(
            source.get("economic_min_improvement", 0.02)
        )
    except (TypeError, ValueError):
        economic_min_improvement = 0.02
    if not np.isfinite(economic_min_improvement):
        economic_min_improvement = 0.02
    try:
        min_paired_test_n = max(2, int(source.get("min_paired_test_n", 10)))
    except (TypeError, ValueError):
        min_paired_test_n = 10

    # The UI exposes these shares.  Keep the documented 70/15/15 defaults,
    # while honoring any valid UI selection for date-based split mode.  An
    # invalid sum is normalized back to the safe default rather than silently
    # creating an empty validation or final-test period.
    try:
        train_fraction = float(source.get("train_fraction", 0.70))
        validation_fraction = float(source.get("validation_fraction", 0.15))
        test_fraction = float(source.get("test_fraction", 0.15))
    except (TypeError, ValueError):
        train_fraction, validation_fraction, test_fraction = 0.70, 0.15, 0.15
    shares = (train_fraction, validation_fraction, test_fraction)
    shares_were_supplied = any(
        key in source
        for key in ("train_fraction", "validation_fraction", "test_fraction")
    )
    if (
        not all(np.isfinite(value) and value > 0 for value in shares)
        or not np.isclose(sum(shares), 1.0, atol=1e-6)
    ):
        if shares_were_supplied:
            raise ValueError(
                "train_fraction, validation_fraction, and test_fraction must "
                "be positive and sum to 1.0"
            )
        train_fraction, validation_fraction, test_fraction = 0.70, 0.15, 0.15

    result = dict(source)
    result.update(
        {
            "horizons": horizons,
            "validation_mode": mode,
            "anchor_mode": anchor_mode,
            "lookback": lookback,
            "pivot_bars": pivot_bars,
            "vol_window": vol_window,
            "normalization": normalization,
            "quantiles": quantiles,
            "large_percentile": large_percentile,
            "abs_return_threshold": abs_return_threshold,
            "rolling_train_sessions": rolling_train_sessions,
            "retrain_sessions": retrain_sessions,
            "max_folds": max_folds,
            "economic_min_improvement": economic_min_improvement,
            "min_paired_test_n": min_paired_test_n,
            "train_fraction": train_fraction,
            "validation_fraction": validation_fraction,
            "test_fraction": test_fraction,
            "fixed_anchor": source.get("fixed_anchor"),
        }
    )
    return result


def ensure_datetime_index(frame: pd.DataFrame) -> pd.DataFrame:
    """Copy and sort a frame by a session datetime index.

    Upstream feature generation promises a sorted datetime index.  Sorting
    here is a defensive boundary for direct API callers and makes all
    chronology guarantees explicit.
    """

    result = frame.copy()
    if not isinstance(result.index, pd.DatetimeIndex):
        result.index = pd.to_datetime(result.index, errors="coerce")
    result = result.loc[~result.index.isna()].sort_index()
    return result


def target_date_column(frame: pd.DataFrame, horizon: int) -> str:
    return f"target_date_{int(horizon)}"


def target_column(frame: pd.DataFrame, horizon: int, normalization: str) -> str:
    if str(normalization).lower() == "none":
        return f"future_area_log_{int(horizon)}"
    return f"future_area_norm_{int(horizon)}"


def eligible_mask(
    frame: pd.DataFrame,
    horizon: int,
    normalization: str = "volatility",
) -> pd.Series:
    """Rows whose primary target and actual target date are known."""

    target = target_column(frame, horizon, normalization)
    date_col = target_date_column(frame, horizon)
    if target not in frame or date_col not in frame:
        return pd.Series(False, index=frame.index)
    target_values = pd.to_numeric(frame[target], errors="coerce")
    target_dates = pd.to_datetime(frame[date_col], errors="coerce")
    return target_values.notna() & target_dates.notna()


def purge_by_target_date(
    frame: pd.DataFrame,
    cutoff: Any,
    horizon: int,
    normalization: str = "volatility",
    *,
    strict: bool = False,
) -> pd.DataFrame:
    """Keep labels realized by ``cutoff``.

    ``strict=False`` permits a label ending on the cutoff date, as it is
    observable at the end of that session.  ``strict=True`` is useful for a
    prediction made at the opening of a session.
    """

    if frame.empty:
        return frame.copy()
    date_col = target_date_column(frame, horizon)
    if date_col not in frame:
        return frame.iloc[0:0].copy()
    cutoff_date = _as_date(cutoff)
    if cutoff_date is None:
        return frame.iloc[0:0].copy()
    dates = pd.to_datetime(frame[date_col], errors="coerce")
    mask = dates < cutoff_date if strict else dates <= cutoff_date
    return frame.loc[mask.fillna(False)].copy()


@dataclass(frozen=True)
class Fold:
    """A chronological fit/evaluation fold."""

    fold: int
    split: str
    train: pd.DataFrame
    evaluation: pd.DataFrame
    fit_cutoff: pd.Timestamp | None
    target_cutoff: pd.Timestamp | None
    start: pd.Timestamp | None
    end: pd.Timestamp | None


def _date_bounds(frame: pd.DataFrame) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if frame.empty:
        return None, None
    dates = pd.to_datetime(frame.index, errors="coerce")
    dates = dates[~dates.isna()]
    if len(dates) == 0:
        return None, None
    return dates.min(), dates.max()


def _safe_slice(frame: pd.DataFrame, positions: Iterable[int]) -> pd.DataFrame:
    positions = list(positions)
    if not positions:
        return frame.iloc[0:0].copy()
    return frame.iloc[positions].copy()


def _split_positions(
    eligible: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[list[int], list[int], list[int]]:
    """Return train, validation, and test row positions."""

    n = len(eligible)
    if n == 0:
        return [], [], []
    mode = config.get("validation_mode", "split")
    if mode == "custom":
        dates = pd.DatetimeIndex(eligible.index)
        train_start = _as_date(config.get("train_start"))
        train_end = _as_date(config.get("train_end"))
        validation_end = _as_date(config.get("validation_end"))
        test_start = _as_date(config.get("test_start"))
        test_end = _as_date(config.get("test_end"))
        train_fraction = float(config.get("train_fraction", 0.70))
        validation_fraction = float(config.get("validation_fraction", 0.15))
        if train_end is None:
            train_end = dates[
                min(n - 1, max(0, int(n * train_fraction) - 1))
            ]
        if validation_end is None:
            validation_end = dates[
                min(
                    n - 1,
                    max(
                        0,
                        int(n * (train_fraction + validation_fraction)) - 1,
                    ),
                )
            ]
        if train_start is None:
            train_start = dates[0]
        if test_start is None:
            after_validation = dates[dates > validation_end]
            test_start = after_validation[0] if len(after_validation) else None
        if train_end is None or validation_end is None:
            raise ValueError("custom date split could not establish boundaries")
        if train_start > train_end:
            raise ValueError("custom train_start must be on or before train_end")
        if train_end >= validation_end:
            raise ValueError(
                "custom train_end must be strictly before validation_end"
            )
        if test_start is None:
            raise ValueError(
                "custom date split requires at least one session after validation_end"
            )
        if test_start <= validation_end:
            raise ValueError(
                "custom test_start must be strictly after validation_end"
            )
        if test_end is not None and test_end < test_start:
            raise ValueError("custom test_end must be on or after test_start")
        train = [
            i
            for i, date in enumerate(dates)
            if train_start <= date <= train_end
        ]
        validation = [
            i
            for i, date in enumerate(dates)
            if train_end < date <= validation_end
        ]
        test = [
            i
            for i, date in enumerate(dates)
            if date >= test_start and (test_end is None or date <= test_end)
        ]
        return train, validation, test

    train_fraction = float(config.get("train_fraction", 0.70))
    validation_fraction = float(config.get("validation_fraction", 0.15))
    n_train = (
        max(1, int(np.floor(n * train_fraction)))
        if n >= 3
        else max(1, n - 1)
    )
    n_validation = max(
        n_train,
        int(np.floor(n * (train_fraction + validation_fraction))),
    )
    if n_validation >= n and n > 1:
        n_validation = n - 1
    if n_train >= n and n > 1:
        n_train = n - 1
    return (
        list(range(0, n_train)),
        list(range(n_train, n_validation)),
        list(range(n_validation, n)),
    )


def build_folds(
    frame: pd.DataFrame,
    horizon: int,
    config: dict[str, Any] | None = None,
) -> tuple[list[Fold], dict[str, Any]]:
    """Build purged chronological folds for one target horizon.

    In split mode the train model is fit once using only labels realized by
    the train cutoff.  In expanding/rolling mode each evaluation block gets a
    separate fit using rows strictly before its evaluation start, with labels
    purged by the corresponding fit cutoff.
    """

    cfg = normalize_config(config)
    data = ensure_datetime_index(frame)
    mask = eligible_mask(data, horizon, cfg["normalization"])
    eligible = data.loc[mask].copy()
    eligible = eligible.sort_index()
    if eligible.empty:
        return [], {
            "eligible": eligible,
            "train_cutoff": None,
            "validation_cutoff": None,
            "test_cutoff": None,
        }

    train_pos, validation_pos, test_pos = _split_positions(eligible, cfg)
    train_base = _safe_slice(eligible, train_pos)
    validation_base = _safe_slice(eligible, validation_pos)
    test_base = _safe_slice(eligible, test_pos)
    train_start, train_end = _date_bounds(train_base)
    validation_start, validation_end = _date_bounds(validation_base)
    test_start, test_end = _date_bounds(test_base)
    metadata = {
        "eligible": eligible,
        "train_cutoff": train_end,
        "validation_cutoff": validation_end,
        "test_cutoff": test_end,
        "train_start": train_start,
        "validation_start": validation_start,
        "test_start": test_start,
    }

    if cfg["validation_mode"] in {"split", "custom"}:
        # Purging is performed on the actual target date, not merely on the
        # observation index.  The same purged fit is deliberately reused for
        # validation and untouched final-test predictions.
        fit_train = purge_by_target_date(
            train_base,
            train_end,
            horizon,
            cfg["normalization"],
        )
        folds: list[Fold] = []
        for fold_number, (name, evaluation) in enumerate(
            (
                ("train", fit_train),
                ("validation", validation_base),
                ("test", test_base),
            ),
            start=0,
        ):
            if evaluation.empty and name != "train":
                continue
            start, end = _date_bounds(evaluation)
            target_dates = (
                pd.to_datetime(
                    evaluation.get(target_date_column(evaluation, horizon)),
                    errors="coerce",
                )
                if not evaluation.empty
                else pd.Series(dtype="datetime64[ns]")
            )
            target_cutoff = (
                target_dates.max() if len(target_dates) and not target_dates.isna().all() else end
            )
            folds.append(
                Fold(
                    fold=fold_number,
                    split=name,
                    train=fit_train.copy(),
                    evaluation=evaluation.copy(),
                    fit_cutoff=train_end,
                    target_cutoff=target_cutoff,
                    start=start,
                    end=end,
                )
            )
        return folds, metadata

    # Walk-forward modes include an in-sample training descriptor for
    # transparency, followed by prequential validation/test blocks.
    folds = []
    initial_fit = purge_by_target_date(
        train_base,
        train_end,
        horizon,
        cfg["normalization"],
    )
    if not initial_fit.empty:
        folds.append(
            Fold(
                fold=0,
                split="train",
                train=initial_fit.copy(),
                evaluation=initial_fit.copy(),
                fit_cutoff=train_end,
                target_cutoff=pd.to_datetime(
                    initial_fit[target_date_column(initial_fit, horizon)],
                    errors="coerce",
                ).max(),
                start=train_start,
                end=train_end,
            )
        )

    # Build blocks over rows after the initial training period.  Blocks are
    # aligned to the first actual test observation, so no block is split into
    # two fits merely because it crosses the validation boundary.
    eval_positions = list(range(len(train_pos), len(eligible)))
    step = cfg["retrain_sessions"]
    validation_length = len(validation_pos)
    segment_bounds = [
        (0, min(validation_length, len(eval_positions))),
        (min(validation_length, len(eval_positions)), len(eval_positions)),
    ]
    requested_specs = []
    for segment_start, segment_end in segment_bounds:
        requested_specs.extend(
            (start, min(start + step, segment_end))
            for start in range(segment_start, segment_end, step)
        )
    block_specs = requested_specs
    walkforward_warning = None
    if len(requested_specs) > cfg["max_folds"]:
        # A cap must never turn into untested holes.  Coarsen each contiguous
        # validation/test segment into blocks that cover every evaluation row.
        if len(segment_bounds) == 2 and all(
            segment_start < segment_end for segment_start, segment_end in segment_bounds
        ):
            total_blocks = max(2, cfg["max_folds"])
        else:
            total_blocks = max(1, cfg["max_folds"])
        lengths = [
            max(0, segment_end - segment_start)
            for segment_start, segment_end in segment_bounds
        ]
        desired = [
            max(1, int(round(total_blocks * length / len(eval_positions))))
            if length
            else 0
            for length in lengths
        ]
        while sum(desired) > total_blocks:
            candidates = [i for i, length in enumerate(lengths) if desired[i] > 1]
            if not candidates:
                break
            index_to_reduce = max(candidates, key=lambda i: desired[i])
            desired[index_to_reduce] -= 1
        while sum(desired) < total_blocks:
            index_to_extend = max(range(len(lengths)), key=lambda i: lengths[i])
            if not lengths[index_to_extend]:
                break
            desired[index_to_extend] += 1
            if desired[index_to_extend] >= lengths[index_to_extend]:
                break
        block_specs = []
        effective_widths = []
        for (segment_start, segment_end), block_count in zip(
            segment_bounds, desired
        ):
            if not (segment_start < segment_end and block_count):
                continue
            width = int(np.ceil((segment_end - segment_start) / block_count))
            effective_widths.append(width)
            block_specs.extend(
                (
                    start,
                    min(start + width, segment_end),
                )
                for start in range(segment_start, segment_end, width)
            )
        cadence_text = ", ".join(str(width) for width in sorted(set(effective_widths)))
        walkforward_warning = (
            f"Horizon {horizon}: max_folds={cfg['max_folds']} coarsened "
            f"retrain cadence from {step} to effective block width(s) "
            f"{cadence_text} sessions; all "
            "walk-forward evaluation dates remain covered."
        )
    if walkforward_warning:
        metadata["walkforward_warning"] = walkforward_warning
    fold_number = 1
    for local_start, local_end in block_specs:
        block_positions = eval_positions[local_start:local_end]
        eval_start_pos = block_positions[0]
        fit_cutoff = eligible.index[eval_start_pos]
        candidate_positions = list(range(0, eval_start_pos))
        if cfg["validation_mode"] == "rolling":
            candidate_positions = candidate_positions[-cfg["rolling_train_sessions"] :]
        candidate = _safe_slice(eligible, candidate_positions)
        candidate = purge_by_target_date(
            candidate,
            fit_cutoff,
            horizon,
            cfg["normalization"],
            strict=True,
        )
        block = _safe_slice(eligible, block_positions)
        if block.empty:
            continue
        # ``test_start`` is the first actual test observation, not the
        # inclusive validation end.  This keeps the boundary stable even when
        # a requested date is a weekend or otherwise absent from the index.
        first_test_date = test_start or pd.Timestamp.max
        for name, piece in (
            (
                "validation",
                block.loc[block.index < first_test_date],
            ),
            ("test", block.loc[block.index >= first_test_date]),
        ):
            if piece.empty:
                continue
            start, end = _date_bounds(piece)
            target_dates = pd.to_datetime(
                piece[target_date_column(piece, horizon)], errors="coerce"
            )
            folds.append(
                Fold(
                    fold=fold_number,
                    split=name,
                    train=candidate.copy(),
                    evaluation=piece.copy(),
                    fit_cutoff=fit_cutoff,
                    target_cutoff=target_dates.max(),
                    start=start,
                    end=end,
                )
            )
            fold_number += 1
    return folds, metadata


def split_summary_rows(
    folds: Iterable[Fold],
    horizon: int,
) -> list[dict[str, Any]]:
    """Convert folds to the public ``splits`` artifact schema."""

    rows = []
    for fold in folds:
        rows.append(
            {
                "horizon": int(horizon),
                "fold": int(fold.fold),
                "split": fold.split,
                "start": fold.start,
                "end": fold.end,
                "n": int(len(fold.evaluation)),
                "fit_cutoff": fold.fit_cutoff,
                "target_cutoff": fold.target_cutoff,
            }
        )
    return rows
