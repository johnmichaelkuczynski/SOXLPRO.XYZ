"""Backend integration tests for the causal Time--Price Area Lab.

These tests intentionally exercise the public feature and target builders
before invoking ``run_lab``.  The generated prices are deterministic but
non-constant, so this suite does not depend on a network data provider.
"""

from __future__ import annotations

import threading
import unittest

import numpy as np
import pandas as pd

from area_lab.features import add_targets, build_features
from area_lab.models import MODEL_NAMES, run_lab
from area_lab.validation import build_folds, normalize_config


class AreaLabModelsIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        count = 600
        index = pd.bdate_range("2020-01-01", periods=count)
        steps = np.arange(count, dtype=float)
        # Several deterministic frequencies avoid constant predictors,
        # duplicate quantile cut points, and one-class labels.
        returns = (
            0.0015 * np.sin(steps / 9.0)
            + 0.006 * np.cos(steps / 17.0)
            + 0.002 * np.sin(steps / 3.0)
        )
        close = 100.0 * np.exp(np.cumsum(np.log1p(returns)))
        cls.ohlc = pd.DataFrame(
            {
                "Open": close * (1.0 + 0.001 * np.sin(steps)),
                "High": close * 1.01,
                "Low": close * 0.99,
                "Close": close,
            },
            index=index,
        )
        cls.features = build_features(
            cls.ohlc,
            {
                "anchor_mode": "low20",
                "lookback": 20,
                "vol_window": 20,
            },
        )
        cls.data = add_targets(cls.features, [1, 5, 60])
        cls.default_config = {"horizons": [1, 5]}
        cls.default_result = run_lab(cls.data, cls.default_config)

    def test_default_artifacts_contain_all_models_splits_and_tables(self) -> None:
        result = self.default_result
        self.assertEqual(set(result["comparison"]["model"]), set(MODEL_NAMES))
        self.assertEqual(set(result["comparison"]["split"]), {"train", "validation", "test"})
        self.assertTrue(
            {"train", "validation", "test"}.issubset(
                set(result["splits"]["split"])
            )
        )
        for horizon in (1, 5):
            split_rows = result["comparison"][
                result["comparison"]["horizon"] == horizon
            ]
            self.assertEqual(
                set(split_rows["split"]),
                {"train", "validation", "test"},
            )
        self.assertFalse(result["calibration"].empty)
        self.assertFalse(result["buckets"].empty)
        self.assertFalse(result["predictions"].empty)
        self.assertIsInstance(result["predictions"].index, pd.DatetimeIndex)
        self.assertTrue(
            {"actual_large", "probability_large", "threshold"}.issubset(
                result["predictions"].columns
            )
        )
        # At least one contemporaneous classification period must have both
        # classes; single-class periods are tested separately below.
        self.assertTrue(result["comparison"]["roc_auc"].notna().any())
        self.assertNotEqual(result["verdict"], "Promising evidence")
        self.assertIn("Paired final-test counts", result["verdict_detail"])

    def test_default_shares_and_target_date_purge_are_explicit(self) -> None:
        result = self.default_result
        self.assertEqual(
            (result["config"]["train_fraction"],
             result["config"]["validation_fraction"],
             result["config"]["test_fraction"]),
            (0.70, 0.15, 0.15),
        )
        for horizon in (1, 5):
            folds, metadata = build_folds(
                self.data, horizon, self.default_config
            )
            by_split = {fold.split: fold for fold in folds}
            self.assertEqual(set(by_split), {"train", "validation", "test"})
            train_fold = by_split["train"]
            train_cutoff = train_fold.fit_cutoff
            target_dates = pd.to_datetime(
                train_fold.train[f"target_date_{horizon}"],
                errors="coerce",
            )
            self.assertTrue((target_dates <= train_cutoff).all())
            eligible = self.data.loc[
                self.data[f"future_area_norm_{horizon}"].notna()
                & self.data[f"target_date_{horizon}"].notna()
            ]
            rows_before_cutoff = eligible.loc[eligible.index <= train_cutoff]
            # At least the forward horizon's crossing labels are purged.
            self.assertGreater(len(rows_before_cutoff), len(train_fold.train))
            self.assertLess(train_fold.end, by_split["validation"].start)
            self.assertLess(by_split["validation"].end, by_split["test"].start)
            self.assertEqual(
                len(train_fold.evaluation),
                int(
                    result["splits"].loc[
                        (result["splits"]["horizon"] == horizon)
                        & (result["splits"]["split"] == "train"),
                        "n",
                    ].iloc[0]
                ),
            )
            self.assertIsNotNone(metadata["test_cutoff"])

    def test_regression_inference_fields_are_finite_when_estimable(self) -> None:
        regression = self.default_result["regression"]
        self.assertTrue(
            {"coefficient", "std_error", "t_stat", "p_value", "r2", "adj_r2"}
            .issubset(regression.columns)
        )
        row = regression.loc[
            (regression["horizon"] == 1)
            & (regression["split"] == "train")
            & (regression["model"] == "Persistence")
            & (regression["term"] == "area_norm")
        ].iloc[0]
        for field in ("coefficient", "std_error", "t_stat", "p_value"):
            self.assertTrue(np.isfinite(float(row[field])), field)
        self.assertTrue(0.0 <= float(row["p_value"]) <= 1.0)
        self.assertIn("area_growth", set(regression["term"]))
        self.assertIn("volatility", set(regression["term"]))

    def test_walk_forward_expanding_and_rolling_are_prequential(self) -> None:
        for mode in ("expanding", "rolling"):
            with self.subTest(mode=mode):
                result = run_lab(
                    self.data,
                    {
                        "horizons": [1],
                        "validation_mode": mode,
                        "retrain_sessions": 63,
                        "rolling_train_sessions": 180,
                        "max_folds": 5,
                    },
                )
                self.assertIn("validation", set(result["splits"]["split"]))
                self.assertIn("test", set(result["splits"]["split"]))
                self.assertGreater(result["splits"]["fold"].nunique(), 2)
                for _, fold in result["splits"].query("fold > 0").iterrows():
                    self.assertLessEqual(fold["fit_cutoff"], fold["start"])

    def test_custom_date_split_respects_requested_ranges(self) -> None:
        index = self.data.index
        config = {
            "horizons": [1],
            "validation_mode": "custom",
            "train_start": index[40].isoformat(),
            "train_end": index[350].isoformat(),
            "validation_end": index[450].isoformat(),
            "test_start": index[451].isoformat(),
            "test_end": index[-1].isoformat(),
        }
        result = run_lab(self.data, config)
        rows = result["splits"]
        self.assertTrue((pd.to_datetime(rows["start"]) >= index[40]).all())
        self.assertTrue((pd.to_datetime(rows["end"]) <= index[-1]).all())
        self.assertTrue(
            (
                pd.to_datetime(
                    rows.loc[rows["split"] == "validation", "start"]
                )
                > index[350]
            ).all()
        )
        self.assertTrue(
            (
                pd.to_datetime(rows.loc[rows["split"] == "test", "start"])
                >= index[451]
            ).all()
        )
        with self.assertRaises(ValueError):
            run_lab(
                self.data,
                {
                    **config,
                    "test_start": index[400].isoformat(),
                },
            )

    def test_walkforward_cap_keeps_contiguous_coverage_and_warns_cadence(self) -> None:
        config = {
            "horizons": [1],
            "validation_mode": "expanding",
            "retrain_sessions": 1,
            "max_folds": 4,
        }
        folds, metadata = build_folds(self.data, 1, config)
        self.assertIn("walkforward_warning", metadata)
        evaluation_dates = pd.DatetimeIndex(
            [date for fold in folds if fold.fold > 0 for date in fold.evaluation.index]
        )
        eligible = self.data.loc[
            self.data["future_area_norm_1"].notna()
            & self.data["target_date_1"].notna()
        ]
        initial_train_end = eligible.index[int(len(eligible) * 0.70) - 1]
        expected = eligible.index[eligible.index > initial_train_end]
        self.assertEqual(set(evaluation_dates), set(expected))
        self.assertEqual(len(evaluation_dates), len(set(evaluation_dates)))
        self.assertLessEqual(len(folds) - 1, normalize_config(config)["max_folds"])
        result = run_lab(self.data, config)
        self.assertTrue(
            any("coarsened retrain cadence" in warning for warning in result["warnings"])
        )

    def test_final_price_perturbation_does_not_change_earlier_predictions(self) -> None:
        index = self.data.index
        config = {
            "horizons": [1, 5],
            "validation_mode": "custom",
            "train_start": index[40].isoformat(),
            "train_end": index[350].isoformat(),
            "validation_end": index[450].isoformat(),
            "test_start": index[451].isoformat(),
            "test_end": index[-1].isoformat(),
        }
        altered = self.ohlc.copy()
        altered.loc[index[-1], ["Open", "High", "Low", "Close"]] *= 1.35
        altered_data = add_targets(
            build_features(altered, {"anchor_mode": "low20", "lookback": 20}),
            [1, 5, 60],
        )
        first = run_lab(self.data, config)["predictions"]
        second = run_lab(altered_data, config)["predictions"]
        fields = ["predicted_area", "threshold"]
        first_early = first[first["split"] == "validation"].set_index(
            ["date", "horizon", "model"]
        )[fields]
        second_early = second[second["split"] == "validation"].set_index(
            ["date", "horizon", "model"]
        )[fields]
        pd.testing.assert_frame_equal(first_early, second_early)

    def test_constant_and_single_class_cases_are_explicit(self) -> None:
        constant = self.data.copy()
        constant["future_area_norm_1"] = 1.0
        result = run_lab(constant, {"horizons": [1]})
        warning_text = " ".join(result["warnings"]).lower()
        self.assertIn("constant", warning_text)
        self.assertIn("single-class", warning_text)
        self.assertTrue(result["comparison"]["roc_auc"].isna().all())
        self.assertTrue(result["comparison"]["r2"].isna().all())

    def test_cancellation_raises_interrupted_error(self) -> None:
        event = threading.Event()
        event.set()
        with self.assertRaises(InterruptedError):
            run_lab(self.data, {"horizons": [1]}, cancel_event=event)

    def test_normalization_none_and_horizon_60_have_bounded_dates(self) -> None:
        sensitivity = run_lab(
            self.data,
            {"horizons": [1, 5], "normalization": "none"},
        )
        self.assertEqual(sensitivity["metadata"]["primary_target"], "future_area_log_h")
        self.assertIn("area_log", set(sensitivity["regression"]["term"]))

        long_horizon = run_lab(self.data, {"horizons": [60]})
        self.assertEqual(set(long_horizon["comparison"]["horizon"]), {60})
        self.assertTrue(
            (
                pd.to_datetime(long_horizon["predictions"]["date"])
                <= self.data.index[-1]
            ).all()
        )
        self.assertTrue(
            pd.to_datetime(self.data["target_date_60"].dropna()).le(
                self.data.index[-1]
            ).all()
        )

    def test_ui_split_shares_are_normalized_and_honored(self) -> None:
        config = normalize_config(
            {
                "train_fraction": 0.60,
                "validation_fraction": 0.20,
                "test_fraction": 0.20,
            }
        )
        self.assertEqual(
            (
                config["train_fraction"],
                config["validation_fraction"],
                config["test_fraction"],
            ),
            (0.60, 0.20, 0.20),
        )
        folds, _ = build_folds(self.data, 1, config)
        rows = {fold.split: len(fold.evaluation) for fold in folds}
        self.assertGreater(rows["validation"], 0)
        self.assertGreater(rows["test"], 0)
        self.assertGreater(rows["train"], rows["validation"])
        with self.assertRaises(ValueError):
            normalize_config(
                {
                    "train_fraction": 0.70,
                    "validation_fraction": 0.20,
                    "test_fraction": 0.20,
                }
            )


if __name__ == "__main__":
    unittest.main()
