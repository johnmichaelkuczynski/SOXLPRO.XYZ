"""Leakage-aware historical models for the Time--Price Area Lab.

This module intentionally contains no UI or forecasting signal generation.
``run_lab`` produces descriptive, chronological research artifacts: every
out-of-sample prediction is made by a model fit only on labels available at
that fit cutoff.  Missing or non-estimable statistics remain ``NaN`` and are
accompanied by a warning rather than being turned into a reassuring zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd

from .metrics import (
    classification_metrics,
    confusion_values,
    paired_loss_inference,
    regression_metrics,
    spearman_correlation,
)
from .validation import (
    Fold,
    build_folds,
    ensure_datetime_index,
    normalize_config,
    split_summary_rows,
    target_column,
)


MODEL_NAMES = (
    "Persistence",
    "Incremental area",
    "Naive persistence",
    "Volatility",
    "Momentum",
    "Combined non-area",
    "Area-enhanced",
)

COMPARISON_COLUMNS = [
    "horizon",
    "split",
    "model",
    "n",
    "r2",
    "mae",
    "rmse",
    "correlation",
    "roc_auc",
    "pr_auc",
    "brier",
    "accuracy",
    "precision",
    "recall",
    "f1",
    "rmse_improvement",
    "roc_auc_improvement",
    "brier_improvement",
]
REGRESSION_COLUMNS = [
    "horizon",
    "split",
    "model",
    "term",
    "coefficient",
    "std_error",
    "t_stat",
    "p_value",
    "r2",
    "adj_r2",
    "n",
    "pearson",
    "spearman",
    "direction",
    "significance",
    "fold",
    "fit_cutoff",
    "training_start",
    "training_end",
    "provenance",
]
BUCKET_COLUMNS = [
    "horizon",
    "split",
    "bucket",
    "n",
    "mean_future_area",
    "median_future_area",
    "mean_abs_return",
    "median_abs_return",
    "mean_signed_return",
    "median_signed_return",
    "prob_large_move",
    "prob_positive",
    "max_drawdown",
    "max_favorable",
]
PREDICTION_COLUMNS = [
    "date",
    "horizon",
    "split",
    "model",
    "current_area",
    "actual_area",
    "predicted_area",
    "actual_large",
    "probability_large",
    "threshold",
]
CALIBRATION_COLUMNS = [
    "horizon",
    "split",
    "model",
    "bin",
    "n",
    "predicted_probability",
    "observed_frequency",
]
COEFFICIENT_COLUMNS = ["horizon", "split", "model", "feature", "coefficient"]
CONFUSION_COLUMNS = ["horizon", "split", "model", "tn", "fp", "fn", "tp"]
SPLIT_COLUMNS = [
    "horizon",
    "fold",
    "split",
    "start",
    "end",
    "n",
    "fit_cutoff",
    "target_cutoff",
]
INFERENCE_COLUMNS = [
    "horizon",
    "n",
    "relative_rmse_gain",
    "mean_squared_loss_gain",
    "ci_low",
    "ci_high",
    "p_value",
]
STABILITY_COLUMNS = ["horizon", "period", "n", "rmse_improvement"]


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _finite(values: Any) -> np.ndarray:
    return pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float)


def _check_cancel(cancel_event: Any) -> None:
    if cancel_event is not None and hasattr(cancel_event, "is_set"):
        if cancel_event.is_set():
            raise InterruptedError("Time–Price Area Lab analysis cancelled")


def _emit_progress(
    progress: Callable[[float, str], Any] | None,
    fraction: float,
    message: str,
) -> None:
    if progress is not None:
        progress(float(max(0.0, min(1.0, fraction))), message)


def _warn(warnings: list[str], message: str) -> None:
    if message not in warnings:
        warnings.append(message)


def _feature_frame(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    """Add internal aliases without altering the public feature definitions."""

    result = frame.copy()
    if config.get("normalization") == "none":
        if "area_log" in result:
            result["_primary_area"] = pd.to_numeric(result["area_log"], errors="coerce")
            result["_primary_growth"] = result["_primary_area"].diff()
    else:
        if "area_norm" in result:
            result["_primary_area"] = pd.to_numeric(
                result["area_norm"], errors="coerce"
            )
        if "area_growth" in result:
            result["_primary_growth"] = pd.to_numeric(
                result["area_growth"], errors="coerce"
            )
        elif "_primary_area" in result:
            result["_primary_growth"] = result["_primary_area"].diff()
    return result


def _feature_names(model: str) -> list[str]:
    """Inputs for the seven public model names."""

    if model == "Persistence":
        return ["_primary_area"]
    if model == "Incremental area":
        return [
            "_primary_area",
            "_primary_growth",
            "volatility",
            "abs_ret_5",
            "abs_ret_20",
            "atr_pct",
        ]
    if model == "Naive persistence":
        return ["volatility", "abs_ret_5"]
    if model == "Volatility":
        return ["volatility", "atr_pct", "abs_ret_5", "abs_ret_20"]
    if model == "Momentum":
        return ["ret_1", "ret_5", "ret_10", "ret_20", "ma_trend"]
    if model == "Combined non-area":
        return [
            "volatility",
            "atr_pct",
            "abs_ret_5",
            "abs_ret_20",
            "ret_1",
            "ret_5",
            "ret_10",
            "ret_20",
            "ma_trend",
        ]
    if model == "Area-enhanced":
        return [
            "volatility",
            "atr_pct",
            "abs_ret_5",
            "abs_ret_20",
            "ret_1",
            "ret_5",
            "ret_10",
            "ret_20",
            "ma_trend",
            "_primary_area",
            "area_signed",
            "_primary_growth",
        ]
    raise ValueError(f"Unknown area-lab model: {model}")


def _display_feature_name(feature: str, normalization: str) -> str:
    """Translate internal aliases to the public research vocabulary."""

    if feature == "_primary_area":
        return "area_log" if normalization == "none" else "area_norm"
    if feature == "_primary_growth":
        return "area_log.diff" if normalization == "none" else "area_growth"
    return feature


@dataclass
class _RegressionFit:
    features: list[str]
    means: np.ndarray
    scales: np.ndarray
    coefficients: np.ndarray
    intercept: float
    train_rows: pd.DataFrame
    y: np.ndarray
    x_standardized: np.ndarray
    rank: int

    def predict(self, frame: pd.DataFrame) -> tuple[pd.Index, np.ndarray]:
        if frame.empty or not self.features:
            return frame.index[:0], np.array([], dtype=float)
        available = frame[self.features].apply(pd.to_numeric, errors="coerce")
        mask = available.notna().all(axis=1)
        if not mask.any():
            return frame.index[:0], np.array([], dtype=float)
        x = available.loc[mask].to_numpy(dtype=float)
        x = (x - self.means) / self.scales
        prediction = self.intercept + x @ self.coefficients
        return available.index[mask], np.asarray(prediction, dtype=float)


@dataclass
class _LogisticFit:
    features: list[str]
    means: np.ndarray
    scales: np.ndarray
    classifier: Any

    def probability(self, frame: pd.DataFrame) -> tuple[pd.Index, np.ndarray]:
        if frame.empty or not self.features:
            return frame.index[:0], np.array([], dtype=float)
        values = frame[self.features].apply(pd.to_numeric, errors="coerce")
        mask = values.notna().all(axis=1)
        if not mask.any():
            return frame.index[:0], np.array([], dtype=float)
        x = (values.loc[mask].to_numpy(dtype=float) - self.means) / self.scales
        classes = list(self.classifier.classes_)
        positive_position = classes.index(1) if 1 in classes else 0
        probability = self.classifier.predict_proba(x)[:, positive_position]
        return values.index[mask], np.asarray(probability, dtype=float)


def _fit_regression(
    frame: pd.DataFrame,
    target: str,
    features: list[str],
    warnings: list[str],
    *,
    model: str,
    horizon: int,
) -> _RegressionFit | None:
    missing = [feature for feature in features if feature not in frame]
    if missing:
        _warn(
            warnings,
            f"{model} horizon {horizon}: unavailable feature(s) {', '.join(missing)}",
        )
        return None
    values = frame[features].apply(pd.to_numeric, errors="coerce")
    y_values = pd.to_numeric(frame[target], errors="coerce")
    valid = values.notna().all(axis=1) & y_values.notna()
    train_rows = frame.loc[valid].copy()
    if train_rows.empty:
        _warn(warnings, f"{model} horizon {horizon}: insufficient complete training rows")
        return None
    x = values.loc[valid].to_numpy(dtype=float)
    y = y_values.loc[valid].to_numpy(dtype=float)
    if len(y) and np.ptp(y) <= np.finfo(float).eps:
        _warn(
            warnings,
            f"{model} horizon {horizon}: constant regression target; R2/correlation not estimable",
        )
    if len(y) <= len(features) + 1:
        _warn(
            warnings,
            f"{model} horizon {horizon}: insufficient observations for {len(features)} predictors",
        )
        return None
    means = np.mean(x, axis=0)
    scales = np.std(x, axis=0, ddof=0)
    constant = scales <= np.finfo(float).eps
    if constant.any():
        _warn(
            warnings,
            f"{model} horizon {horizon}: constant predictor(s) omitted from fit",
        )
        keep = ~constant
        features = [feature for feature, use in zip(features, keep) if use]
        x = x[:, keep]
        means = means[keep]
        scales = scales[keep]
    if not features:
        _warn(warnings, f"{model} horizon {horizon}: all predictors are constant")
        return None
    x_standardized = (x - means) / scales
    design = np.column_stack([np.ones(len(y)), x_standardized])
    rank = int(np.linalg.matrix_rank(design))
    if rank < design.shape[1]:
        _warn(warnings, f"{model} horizon {horizon}: singular design matrix")
    # A small, fixed ridge term makes prediction well-defined in near
    # collinear benchmark designs without using validation or test data.
    alpha = 1e-8
    gram = design.T @ design
    penalty = np.eye(gram.shape[0]) * alpha
    penalty[0, 0] = 0.0
    try:
        coefficients_all = np.linalg.solve(
            gram + penalty, design.T @ (y - np.mean(y))
        )
    except np.linalg.LinAlgError:
        _warn(warnings, f"{model} horizon {horizon}: singular fit; pseudoinverse used")
        coefficients_all = np.linalg.pinv(gram + penalty) @ design.T @ (y - np.mean(y))
    intercept = float(np.mean(y))
    return _RegressionFit(
        features=features,
        means=means,
        scales=scales,
        coefficients=np.asarray(coefficients_all[1:], dtype=float),
        intercept=intercept,
        train_rows=train_rows,
        y=y,
        x_standardized=x_standardized,
        rank=rank,
    )


def _fit_logistic(
    frame: pd.DataFrame,
    target: str,
    features: list[str],
    threshold: float,
    warnings: list[str],
    *,
    model: str,
    horizon: int,
) -> _LogisticFit | None:
    missing = [feature for feature in features if feature not in frame]
    if missing:
        return None
    values = frame[features].apply(pd.to_numeric, errors="coerce")
    target_values = pd.to_numeric(frame[target], errors="coerce")
    valid = values.notna().all(axis=1) & target_values.notna()
    if valid.sum() < len(features) + 3:
        _warn(
            warnings,
            f"{model} horizon {horizon}: insufficient rows for classification",
        )
        return None
    x = values.loc[valid].to_numpy(dtype=float)
    y_numeric = target_values.loc[valid].to_numpy(dtype=float)
    y = (y_numeric > threshold).astype(int)
    if len(np.unique(y)) < 2:
        _warn(
            warnings,
            f"{model} horizon {horizon}: single-class classification target",
        )
        return None
    means = np.mean(x, axis=0)
    scales = np.std(x, axis=0, ddof=0)
    keep = scales > np.finfo(float).eps
    if not keep.all():
        _warn(
            warnings,
            f"{model} horizon {horizon}: constant classification predictor(s) omitted",
        )
    if not keep.any():
        _warn(warnings, f"{model} horizon {horizon}: no varying classification predictors")
        return None
    features = [feature for feature, use in zip(features, keep) if use]
    means, scales, x = means[keep], scales[keep], x[:, keep]
    try:
        from sklearn.linear_model import LogisticRegression

        classifier = LogisticRegression(
            max_iter=1000,
            solver="lbfgs",
            class_weight=None,
        )
        classifier.fit((x - means) / scales, y)
    except (ImportError, ValueError, FloatingPointError) as exc:
        _warn(warnings, f"{model} horizon {horizon}: logistic fit unavailable ({exc})")
        return None
    return _LogisticFit(features, means, scales, classifier)


def _inferential_rows(
    fit: _RegressionFit,
    *,
    horizon: int,
    split: str,
    model: str,
    normalization: str,
    fold: int,
    fit_cutoff: Any,
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Statsmodels OLS/HAC table for the fit's training sample."""

    terms = [
        "intercept",
        *[
            _display_feature_name(feature, normalization)
            for feature in fit.features
        ],
    ]
    result: list[dict[str, Any]] = []
    metric = regression_metrics(
        fit.y,
        fit.intercept + fit.x_standardized @ fit.coefficients,
    )
    n = len(fit.y)
    k = len(fit.features)
    adj_r2 = np.nan
    if n > k + 1 and np.isfinite(metric["r2"]):
        adj_r2 = 1.0 - (1.0 - metric["r2"]) * (n - 1) / (n - k - 1)
    pearson = np.nan
    spearman = np.nan
    if fit.features:
        area = fit.train_rows[fit.features[0]]
        pearson = regression_metrics(area, fit.y)["correlation"]
        spearman = spearman_correlation(area, fit.y)

    params = np.full(len(terms), np.nan)
    standard_errors = np.full(len(terms), np.nan)
    t_stats = np.full(len(terms), np.nan)
    p_values = np.full(len(terms), np.nan)
    if fit.rank < len(terms):
        _warn(
            warnings,
            f"{model} horizon {horizon} {split}: inferential design is singular",
        )
    else:
        try:
            import statsmodels.api as sm

            design = sm.add_constant(fit.x_standardized, has_constant="add")
            ols = sm.OLS(fit.y, design).fit(
                cov_type="HAC",
                cov_kwds={"maxlags": max(1, int(horizon))},
            )
            params = np.asarray(ols.params, dtype=float)
            standard_errors = np.asarray(ols.bse, dtype=float)
            t_stats = np.asarray(ols.tvalues, dtype=float)
            p_values = np.asarray(ols.pvalues, dtype=float)
        except (ImportError, ValueError, np.linalg.LinAlgError) as exc:
            # Keep coefficient rows explicit but not falsely significant.
            _warn(
                warnings,
                f"{model} horizon {horizon} {split}: HAC inference unavailable ({exc})",
            )

    for i, term in enumerate(terms):
        coefficient = params[i] if i < len(params) else np.nan
        p_value = p_values[i] if i < len(p_values) else np.nan
        if not np.isfinite(coefficient):
            direction = "not estimable"
            significance = "not estimable"
        else:
            direction = "positive" if coefficient > 0 else "negative" if coefficient < 0 else "none"
            significance = (
                "significant"
                if np.isfinite(p_value) and p_value < 0.05
                else "not significant"
            )
        result.append(
            {
                "horizon": horizon,
                "split": split,
                "model": model,
                "term": term,
                "coefficient": coefficient,
                "std_error": standard_errors[i],
                "t_stat": t_stats[i],
                "p_value": p_value,
                "r2": metric["r2"],
                "adj_r2": adj_r2,
                "n": n,
                "pearson": pearson,
                "spearman": spearman,
                "direction": direction,
                "significance": significance,
                "fold": fold,
                "fit_cutoff": fit_cutoff,
                "training_start": fit.train_rows.index.min(),
                "training_end": fit.train_rows.index.max(),
                "provenance": "training_fit_diagnostic",
            }
        )
    return result


def _append_prediction_rows(
    records: list[dict[str, Any]],
    index: pd.Index,
    current_area: np.ndarray,
    area: np.ndarray,
    predicted: np.ndarray,
    probability_by_date: dict[Any, float],
    threshold_by_date: dict[Any, float],
    target_by_date: dict[Any, int],
    *,
    horizon: int,
    split: str,
    model: str,
) -> None:
    for date, current, actual, prediction in zip(
        index, current_area, area, predicted
    ):
        records.append(
            {
                "date": date,
                "horizon": horizon,
                "split": split,
                "model": model,
                "current_area": float(current),
                "actual_area": float(actual),
                "predicted_area": float(prediction),
                "actual_large": target_by_date.get(date, np.nan),
                "probability_large": probability_by_date.get(date, np.nan),
                "threshold": threshold_by_date.get(date, np.nan),
            }
        )


def _bucket_records(
    fold: Fold,
    *,
    horizon: int,
    target: str,
    config: dict[str, Any],
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Compute buckets using cut points learned from this fold's train rows."""

    area_column = "_primary_area"
    required = [
        area_column,
        target,
        f"future_abs_return_{horizon}",
        f"future_signed_return_{horizon}",
    ]
    if any(column not in fold.train for column in required):
        _warn(warnings, f"Horizon {horizon} {fold.split}: bucket inputs unavailable")
        return []
    train_area = pd.to_numeric(fold.train[area_column], errors="coerce").dropna()
    if len(train_area) < config["quantiles"]:
        _warn(warnings, f"Horizon {horizon} {fold.split}: insufficient bucket training rows")
        return []
    quantile_levels = np.linspace(0, 1, config["quantiles"] + 1)[1:-1]
    edges_inner = np.unique(np.nanquantile(train_area.to_numpy(), quantile_levels))
    if len(edges_inner) < len(quantile_levels):
        _warn(
            warnings,
            f"Horizon {horizon} {fold.split}: repeated area values reduced bucket cutpoints",
        )
    edges = np.concatenate(([-np.inf], edges_inner, [np.inf]))
    evaluation = fold.evaluation.copy()
    values = pd.DataFrame(index=evaluation.index)
    for column in required:
        values[column] = pd.to_numeric(evaluation[column], errors="coerce")
    values["forward_drawdown"] = pd.to_numeric(
        evaluation.get(f"forward_drawdown_{horizon}"), errors="coerce"
    )
    values["forward_favorable"] = pd.to_numeric(
        evaluation.get(f"forward_favorable_{horizon}"), errors="coerce"
    )
    values = values.dropna(subset=[area_column, target])
    if values.empty:
        return []
    values["bucket"] = np.digitize(values[area_column], edges_inner, right=True) + 1
    output = []
    # Keep one record per observation.  Aggregating fold medians or extrema
    # later would not equal the requested pooled median/minimum/maximum.
    for _, observation in values.iterrows():
        output.append(
            {
                "horizon": horizon,
                "split": fold.split,
                "bucket": int(observation["bucket"]),
                "future_area": observation[target],
                "abs_return": observation[f"future_abs_return_{horizon}"],
                "signed_return": observation[f"future_signed_return_{horizon}"],
                "forward_drawdown": observation["forward_drawdown"],
                "forward_favorable": observation["forward_favorable"],
                "abs_return_threshold": config["abs_return_threshold"],
            }
        )
    return output


def _aggregate_buckets(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return _empty(BUCKET_COLUMNS)
    frame = pd.DataFrame(records)
    output = []
    grouped = frame.groupby(["horizon", "split", "bucket"], sort=True)
    for (horizon, split, bucket), group in grouped:
        future_area = pd.to_numeric(group["future_area"], errors="coerce")
        abs_return = pd.to_numeric(group["abs_return"], errors="coerce")
        signed_return = pd.to_numeric(group["signed_return"], errors="coerce")
        drawdown = pd.to_numeric(group["forward_drawdown"], errors="coerce")
        favorable = pd.to_numeric(group["forward_favorable"], errors="coerce")
        n = int(future_area.notna().sum())
        row = {
            "horizon": horizon,
            "split": split,
            "bucket": bucket,
            "n": n,
            "mean_future_area": future_area.mean(),
            "median_future_area": future_area.median(),
            "mean_abs_return": abs_return.mean(),
            "median_abs_return": abs_return.median(),
            "mean_signed_return": signed_return.mean(),
            "median_signed_return": signed_return.median(),
            "prob_large_move": (
                float(
                    (
                        abs_return.loc[abs_return.notna()]
                        > float(group["abs_return_threshold"].iloc[0])
                    ).mean()
                )
                if abs_return.notna().any()
                else np.nan
            ),
            "prob_positive": (
                float((signed_return.loc[signed_return.notna()] > 0).mean())
                if signed_return.notna().any()
                else np.nan
            ),
            "max_drawdown": drawdown.min() if drawdown.notna().any() else np.nan,
            "max_favorable": favorable.max() if favorable.notna().any() else np.nan,
        }
        output.append(row)
    return pd.DataFrame(output, columns=BUCKET_COLUMNS)


def _calibration_frame(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if predictions.empty:
        return _empty(CALIBRATION_COLUMNS)
    for keys, group in predictions.groupby(["horizon", "split", "model"], sort=True):
        group = group.dropna(subset=["probability_large", "actual_large"])
        if group.empty:
            continue
        probabilities = group["probability_large"].to_numpy(dtype=float)
        labels = group["actual_large"].to_numpy(dtype=float)
        bins = np.minimum(9, np.floor(np.clip(probabilities, 0, 1) * 10).astype(int))
        for bin_number in sorted(set(bins)):
            selected = bins == bin_number
            rows.append(
                {
                    "horizon": keys[0],
                    "split": keys[1],
                    "model": keys[2],
                    "bin": int(bin_number),
                    "n": int(selected.sum()),
                    "predicted_probability": float(np.mean(probabilities[selected])),
                    "observed_frequency": float(np.mean(labels[selected])),
                }
            )
    return pd.DataFrame(rows, columns=CALIBRATION_COLUMNS)


def _comparison_frame(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return _empty(COMPARISON_COLUMNS)
    rows = []
    groups = predictions.groupby(["horizon", "split", "model"], sort=True)
    for keys, group in groups:
        regression = regression_metrics(group["actual_area"], group["predicted_area"])
        classification = classification_metrics(
            group["actual_large"], group["probability_large"]
        )
        rows.append(
            {
                "horizon": keys[0],
                "split": keys[1],
                "model": keys[2],
                "n": regression["n"],
                "r2": regression["r2"],
                "mae": regression["mae"],
                "rmse": regression["rmse"],
                "correlation": regression["correlation"],
                "roc_auc": classification["roc_auc"],
                "pr_auc": classification["pr_auc"],
                "brier": classification["brier"],
                "accuracy": classification["accuracy"],
                "precision": classification["precision"],
                "recall": classification["recall"],
                "f1": classification["f1"],
                "rmse_improvement": np.nan,
                "roc_auc_improvement": np.nan,
                "brier_improvement": np.nan,
            }
        )
    result = pd.DataFrame(rows, columns=COMPARISON_COLUMNS)

    # Performance deltas use a date inner join, rather than independently
    # computed denominators, so missing warmup rows cannot manufacture gains.
    baseline_name = "Combined non-area"
    for (horizon, split), all_rows in predictions.groupby(
        ["horizon", "split"], sort=False
    ):
        baseline = all_rows[all_rows["model"] == baseline_name].set_index("date")
        if baseline.empty:
            continue
        for model in all_rows["model"].dropna().unique():
            if model == baseline_name:
                continue
            candidate = all_rows[all_rows["model"] == model].set_index("date")
            matched = candidate.join(
                baseline[["predicted_area", "probability_large", "actual_large"]],
                lsuffix="_candidate",
                rsuffix="_baseline",
                how="inner",
            )
            if matched.empty:
                continue
            reg_candidate = regression_metrics(
                matched["actual_area"], matched["predicted_area_candidate"]
            )
            reg_baseline = regression_metrics(
                matched["actual_area"], matched["predicted_area_baseline"]
            )
            cls_candidate = classification_metrics(
                matched["actual_large_candidate"],
                matched["probability_large_candidate"],
            )
            cls_baseline = classification_metrics(
                matched["actual_large_baseline"],
                matched["probability_large_baseline"],
            )
            selector = (
                (result["horizon"] == horizon)
                & (result["split"] == split)
                & (result["model"] == model)
            )
            result.loc[selector, "rmse_improvement"] = (
                reg_baseline["rmse"] - reg_candidate["rmse"]
            )
            if np.isfinite(cls_candidate["roc_auc"]) and np.isfinite(
                cls_baseline["roc_auc"]
            ):
                result.loc[selector, "roc_auc_improvement"] = (
                    cls_candidate["roc_auc"] - cls_baseline["roc_auc"]
                )
            if np.isfinite(cls_candidate["brier"]) and np.isfinite(cls_baseline["brier"]):
                result.loc[selector, "brier_improvement"] = (
                    cls_baseline["brier"] - cls_candidate["brier"]
                )
    return result


def _confusion_frame(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if predictions.empty:
        return _empty(CONFUSION_COLUMNS)
    for keys, group in predictions.groupby(["horizon", "split", "model"], sort=True):
        values = confusion_values(group["actual_large"], group["probability_large"])
        if all(pd.isna(value) for value in values.values()):
            continue
        rows.append(
            {
                "horizon": keys[0],
                "split": keys[1],
                "model": keys[2],
                **values,
            }
        )
    return pd.DataFrame(rows, columns=CONFUSION_COLUMNS)


def _final_inference(
    predictions: pd.DataFrame,
    config: dict[str, Any],
    warnings: list[str],
) -> pd.DataFrame:
    rows = []
    if predictions.empty:
        return _empty(INFERENCE_COLUMNS)
    for horizon in config["horizons"]:
        final = predictions[
            (predictions["horizon"] == horizon)
            & (predictions["split"] == "test")
        ]
        baseline = final[final["model"] == "Combined non-area"].set_index("date")
        candidate = final[final["model"] == "Area-enhanced"].set_index("date")
        if baseline.empty or candidate.empty:
            _warn(warnings, f"Horizon {horizon}: insufficient final-test pairing for inference")
            rows.append(
                {
                    "horizon": horizon,
                    "n": 0,
                    "relative_rmse_gain": np.nan,
                    "mean_squared_loss_gain": np.nan,
                    "ci_low": np.nan,
                    "ci_high": np.nan,
                    "p_value": np.nan,
                }
            )
            continue
        matched = candidate[["actual_area", "predicted_area"]].join(
            baseline[["predicted_area"]],
            lsuffix="_candidate",
            rsuffix="_baseline",
            how="inner",
        )
        stats = paired_loss_inference(
            matched["actual_area"],
            matched["predicted_area_baseline"],
            matched["predicted_area_candidate"],
            horizon,
            n_bootstrap=int(config.get("bootstrap_samples", 200)),
            seed=int(config.get("random_seed", 173)) + int(horizon),
        )
        rows.append({"horizon": horizon, **stats})
    return pd.DataFrame(rows, columns=INFERENCE_COLUMNS)


def _stability_frame(
    predictions: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    rows = []
    if predictions.empty:
        return _empty(STABILITY_COLUMNS)
    for horizon in config["horizons"]:
        final = predictions[
            (predictions["horizon"] == horizon)
            & (predictions["split"] == "test")
        ]
        baseline = final[final["model"] == "Combined non-area"].set_index("date")
        candidate = final[final["model"] == "Area-enhanced"].set_index("date")
        if baseline.empty or candidate.empty:
            continue
        matched = candidate[["actual_area", "predicted_area"]].join(
            baseline[["predicted_area"]],
            lsuffix="_candidate",
            rsuffix="_baseline",
            how="inner",
        ).sort_index()
        if matched.empty:
            continue
        chunks = np.array_split(matched, 3)
        for period, chunk in enumerate(chunks, start=1):
            if chunk.empty:
                continue
            candidate_rmse = regression_metrics(
                chunk["actual_area"], chunk["predicted_area_candidate"]
            )["rmse"]
            baseline_rmse = regression_metrics(
                chunk["actual_area"], chunk["predicted_area_baseline"]
            )["rmse"]
            improvement = (
                (baseline_rmse - candidate_rmse) / baseline_rmse
                if np.isfinite(baseline_rmse) and baseline_rmse > np.finfo(float).eps
                else np.nan
            )
            rows.append(
                {
                    "horizon": horizon,
                    "period": period,
                    "n": len(chunk),
                    "rmse_improvement": improvement,
                }
            )
    return pd.DataFrame(rows, columns=STABILITY_COLUMNS)


def _verdict(
    comparison: pd.DataFrame,
    inference: pd.DataFrame,
    stability: pd.DataFrame,
    config: dict[str, Any],
    warnings: list[str],
) -> tuple[str, str]:
    paired_detail = ""
    if not inference.empty and {"horizon", "n"}.issubset(inference.columns):
        paired_detail = " Paired final-test counts: " + ", ".join(
            f"h{int(row.horizon)}={int(row.n)}"
            for row in inference.itertuples(index=False)
        ) + "."
    if comparison.empty or inference.empty:
        return (
            "Insufficient evidence",
            "No estimable final out-of-sample comparison was available; missing statistics are not evidence of a relationship."
            + paired_detail,
        )
    final = comparison[comparison["split"] == "test"]
    min_n = int(config.get("min_paired_test_n", 10))
    estimable = inference.loc[
        (pd.to_numeric(inference["n"], errors="coerce") >= min_n)
        & np.isfinite(pd.to_numeric(inference["relative_rmse_gain"], errors="coerce"))
        & np.isfinite(pd.to_numeric(inference["ci_low"], errors="coerce"))
        & np.isfinite(pd.to_numeric(inference["ci_high"], errors="coerce"))
        & np.isfinite(pd.to_numeric(inference["p_value"], errors="coerce"))
    ]
    if final.empty or estimable.empty:
        return (
            "Insufficient evidence",
            "The untouched final test period did not contain enough paired predictions "
            "with an estimable dependence-aware confidence interval for an evidence "
            "assessment." + paired_detail,
        )
    assessments: list[dict[str, Any]] = []
    for row in estimable.itertuples(index=False):
        horizon = int(row.horizon)
        horizon_final = final[final["horizon"] == horizon]
        enhanced = horizon_final[horizon_final["model"] == "Area-enhanced"]
        baseline = horizon_final[horizon_final["model"] == "Combined non-area"]
        if enhanced.empty or baseline.empty:
            continue
        area_brier = pd.to_numeric(
            enhanced["brier"], errors="coerce"
        ).dropna()
        base_brier = pd.to_numeric(
            baseline["brier"], errors="coerce"
        ).dropna()
        calibration_ok = bool(
            len(area_brier)
            and len(base_brier)
            and float(area_brier.iloc[0]) <= float(base_brier.iloc[0])
        )
        horizon_stability = stability[stability["horizon"] == horizon]
        positive_periods = int(
            (
                pd.to_numeric(
                    horizon_stability["rmse_improvement"], errors="coerce"
                )
                > 0
            ).sum()
        )
        assessments.append(
            {
                "horizon": horizon,
                "gain": float(row.relative_rmse_gain),
                "ci_low": float(row.ci_low),
                "economically_relevant": (
                    float(row.relative_rmse_gain)
                    >= float(config["economic_min_improvement"])
                    and float(row.ci_low) > 0
                ),
                "calibration_ok": calibration_ok,
                "positive_periods": positive_periods,
            }
        )
    if not assessments:
        return (
            "No evidence",
            "No matched area-enhanced versus combined-baseline final-test rows "
            "were available at an estimable horizon." + paired_detail,
        )

    robust = [
        item
        for item in assessments
        if item["economically_relevant"]
        and item["positive_periods"] >= 2
        and item["calibration_ok"]
    ]
    any_positive = any(item["gain"] > 0 for item in assessments)
    any_economic = any(item["economically_relevant"] for item in assessments)
    fixed_anchor = config.get("anchor_mode") == "fixed"
    if robust:
        # A single run has no actual cross-anchor replication artifact.  Do
        # not let a user-supplied config flag promote it to "Promising".
        verdict = "Weak evidence"
        detail = (
            "Positive paired final-test gains clear the configured economic "
            "threshold and are stable in at least two unseen subperiods at the "
            "same horizon, but this run contains no actual cross-anchor "
            "replication artifact; Promising evidence is therefore not assigned."
            + (
                " The fixed anchor remains exploratory."
                if fixed_anchor
                else ""
            )
        )
    elif any_positive and any_economic:
        verdict = "Weak evidence"
        detail = (
            "A positive out-of-sample gain is present, but it is not robustly "
            "stable across unseen subperiods at the same horizon."
        )
    elif any_positive:
        verdict = "Weak evidence"
        detail = (
            "A small or unstable out-of-sample improvement was observed below "
            "the configured economic relevance and confidence requirements."
        )
    else:
        verdict = "No evidence"
        detail = (
            "Area variables did not improve final out-of-sample RMSE relative "
            "to the combined non-area baseline."
        )
    detail += paired_detail
    if any("single-class" in warning for warning in warnings):
        detail += " Classification has at least one single-class period and is not estimable there."
    return verdict, detail


def run_lab(
    features_with_targets: pd.DataFrame,
    config: dict[str, Any] | None,
    progress: Callable[[float, str], Any] | None = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    """Run all benchmark, area, bucket, classification, and inference tests.

    Parameters are intentionally data-frame based so callers can persist and
    rerender the exact result without recomputing feature engineering.
    """

    cfg = normalize_config(config)
    results: dict[str, Any] = {
        "comparison": _empty(COMPARISON_COLUMNS),
        "regression": _empty(REGRESSION_COLUMNS),
        "buckets": _empty(BUCKET_COLUMNS),
        "predictions": _empty(PREDICTION_COLUMNS),
        "calibration": _empty(CALIBRATION_COLUMNS),
        "coefficients": _empty(COEFFICIENT_COLUMNS),
        "confusion": _empty(CONFUSION_COLUMNS),
        "splits": _empty(SPLIT_COLUMNS),
        "warnings": [],
        "verdict": "Insufficient evidence",
        "verdict_detail": "No analysis has been estimable yet.",
        "config": cfg,
        "inference": _empty(INFERENCE_COLUMNS),
        "stability": _empty(STABILITY_COLUMNS),
        "metadata": {
            "primary_target": (
                "future_area_log_h"
                if cfg["normalization"] == "none"
                else "future_area_norm_h"
            ),
            "models": list(MODEL_NAMES),
            "validation_mode": cfg["validation_mode"],
            "label_purging": "fit rows require target_date_h <= fit_cutoff",
            "anchor_reset_note": (
                "Each future area target comes from the future row's own causal "
                "anchor; anchors can reset between t and t+h."
            ),
        },
    }
    warnings: list[str] = results["warnings"]
    if not isinstance(features_with_targets, pd.DataFrame):
        raise TypeError("features_with_targets must be a pandas DataFrame")
    _check_cancel(cancel_event)
    if features_with_targets.empty:
        _warn(warnings, "No feature rows were supplied")
        results["verdict_detail"] = "No feature rows were supplied."
        results["predictions"].index = pd.DatetimeIndex([], name="date")
        return results

    data = _feature_frame(
        ensure_datetime_index(features_with_targets),
        cfg,
    )
    inherited_warnings = features_with_targets.attrs.get("data_quality_warnings", [])
    if isinstance(inherited_warnings, (list, tuple)):
        for warning in inherited_warnings:
            _warn(warnings, str(warning))
    if cfg.get("anchor_mode") == "fixed":
        _warn(
            warnings,
            "Fixed calendar anchors are exploratory and are not replication evidence.",
        )
    prediction_records: list[dict[str, Any]] = []
    regression_records: list[dict[str, Any]] = []
    coefficient_records: list[dict[str, Any]] = []
    bucket_records: list[dict[str, Any]] = []
    split_records: list[dict[str, Any]] = []
    total_steps = max(1, len(cfg["horizons"]) * 3 * len(MODEL_NAMES))
    completed_steps = 0

    for horizon_position, horizon in enumerate(cfg["horizons"]):
        _check_cancel(cancel_event)
        target = target_column(data, horizon, cfg["normalization"])
        folds, _metadata = build_folds(data, horizon, cfg)
        if _metadata.get("walkforward_warning"):
            _warn(warnings, str(_metadata["walkforward_warning"]))
        split_records.extend(split_summary_rows(folds, horizon))
        if not folds:
            _warn(
                warnings,
                f"Horizon {horizon}: no eligible target rows or target columns",
            )
            _emit_progress(
                progress,
                (horizon_position + 1) / len(cfg["horizons"]),
                f"Horizon {horizon}: no eligible rows",
            )
            continue
        # Buckets use fold-specific frozen training edges, including for final
        # test rows.  No final-test target is used to choose an edge.
        for fold in folds:
            _check_cancel(cancel_event)
            bucket_records.extend(
                _bucket_records(
                    fold,
                    horizon=horizon,
                    target=target,
                    config=cfg,
                    warnings=warnings,
                )
            )
            for model_position, model in enumerate(MODEL_NAMES):
                _check_cancel(cancel_event)
                names = _feature_names(model)
                fit = _fit_regression(
                    fold.train,
                    target,
                    names,
                    warnings,
                    model=model,
                    horizon=horizon,
                )
                if fit is not None:
                    regression_records.extend(
                        _inferential_rows(
                            fit,
                            horizon=horizon,
                            split=fold.split,
                            model=model,
                            normalization=cfg["normalization"],
                            fold=fold.fold,
                            fit_cutoff=fold.fit_cutoff,
                            warnings=warnings,
                        )
                    )
                    coefficient_records.append(
                        {
                            "horizon": horizon,
                            "split": fold.split,
                            "model": model,
                            "feature": "intercept",
                            "coefficient": fit.intercept,
                        }
                    )
                    for feature, coefficient in zip(fit.features, fit.coefficients):
                        coefficient_records.append(
                            {
                                "horizon": horizon,
                                "split": fold.split,
                                "model": model,
                                "feature": _display_feature_name(
                                    feature, cfg["normalization"]
                                ),
                                "coefficient": coefficient,
                            }
                        )
                    eval_index, predicted = fit.predict(fold.evaluation)
                    if len(eval_index):
                        actual = pd.to_numeric(
                            fold.evaluation.loc[eval_index, target], errors="coerce"
                        ).to_numpy(dtype=float)
                        current_area = pd.to_numeric(
                            fold.evaluation.loc[eval_index, "_primary_area"],
                            errors="coerce",
                        ).to_numpy(dtype=float)
                        # Thresholds are fitted from this fold's training target
                        # only, including in the final untouched test fold.
                        training_target = pd.to_numeric(
                            fold.train[target], errors="coerce"
                        ).dropna()
                        threshold = (
                            float(
                                np.nanpercentile(
                                    training_target.to_numpy(),
                                    cfg["large_percentile"],
                                )
                            )
                            if len(training_target)
                            else np.nan
                        )
                        threshold_by_date = {
                            date: threshold for date in eval_index
                        }
                        target_by_date = {
                            date: int(
                                value > threshold
                            )
                            if np.isfinite(threshold) and np.isfinite(value)
                            else np.nan
                            for date, value in zip(eval_index, actual)
                        }
                        logistic = _fit_logistic(
                            fold.train,
                            target,
                            names,
                            threshold,
                            warnings,
                            model=model,
                            horizon=horizon,
                        )
                        probability_by_date: dict[Any, float] = {}
                        if logistic is not None:
                            for feature, coefficient in zip(
                                logistic.features,
                                logistic.classifier.coef_[0],
                            ):
                                coefficient_records.append(
                                    {
                                        "horizon": horizon,
                                        "split": fold.split,
                                        "model": model,
                                        "feature": (
                                            "classification:"
                                            + _display_feature_name(
                                                feature, cfg["normalization"]
                                            )
                                        ),
                                        "coefficient": float(coefficient),
                                    }
                                )
                            probability_index, probabilities = logistic.probability(
                                fold.evaluation
                            )
                            probability_by_date = {
                                date: float(probability)
                                for date, probability in zip(
                                    probability_index, probabilities
                                )
                            }
                        _append_prediction_rows(
                            prediction_records,
                            eval_index,
                            current_area,
                            actual,
                            predicted,
                            probability_by_date,
                            threshold_by_date,
                            target_by_date,
                            horizon=horizon,
                            split=fold.split,
                            model=model,
                        )
                completed_steps += 1
                _emit_progress(
                    progress,
                    (horizon_position + completed_steps / max(1, len(folds) * len(MODEL_NAMES)))
                    / len(cfg["horizons"]),
                    f"Horizon {horizon}, {model}, {fold.split}",
                )

    if prediction_records:
        predictions = pd.DataFrame(prediction_records, columns=PREDICTION_COLUMNS)
        predictions["date"] = pd.to_datetime(predictions["date"], errors="coerce")
        predictions = predictions.set_index("date")
        # Public artifact retains date both as a column and as its datetime
        # index.  This makes CSV persistence and date-index plotting equivalent.
        predictions.insert(0, "date", predictions.index)
        results["predictions"] = predictions[PREDICTION_COLUMNS]
    else:
        results["predictions"] = _empty(PREDICTION_COLUMNS)
        results["predictions"].index = pd.DatetimeIndex([], name="date")

    results["comparison"] = _comparison_frame(results["predictions"])
    results["regression"] = pd.DataFrame(
        regression_records, columns=REGRESSION_COLUMNS
    )
    results["coefficients"] = pd.DataFrame(
        coefficient_records, columns=COEFFICIENT_COLUMNS
    )
    results["buckets"] = _aggregate_buckets(bucket_records)
    results["calibration"] = _calibration_frame(results["predictions"])
    results["confusion"] = _confusion_frame(results["predictions"])
    results["splits"] = pd.DataFrame(split_records, columns=SPLIT_COLUMNS)
    results["inference"] = _final_inference(
        results["predictions"],
        cfg,
        warnings,
    )
    results["stability"] = _stability_frame(results["predictions"], cfg)
    verdict, detail = _verdict(
        results["comparison"],
        results["inference"],
        results["stability"],
        cfg,
        warnings,
    )
    results["verdict"] = verdict
    results["verdict_detail"] = detail
    _emit_progress(progress, 1.0, "Area predictiveness analysis complete")
    return results


__all__ = [
    "MODEL_NAMES",
    "run_lab",
]
