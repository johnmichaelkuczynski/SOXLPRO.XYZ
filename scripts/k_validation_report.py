"""Freeze before evaluate; refuse changed inputs/code or overwriting released evidence."""
from pathlib import Path
import hashlib
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from k_validation import PROTOCOL, snapshots, fit_cutoffs, assign_ranks, outcomes, summarize

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/soxl_signal_study_prices.csv"
OUT = ROOT / "reports/k_validation"


def fingerprint():
    files = ["docs/soxl_signal_study_prices.csv", "mean_reversion_model.py",
             "k_validation.py", "scripts/k_validation_report.py"]
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files}


def main(command):
    OUT.mkdir(parents=True, exist_ok=True)
    lock = OUT / "protocol.json"
    if command == "freeze":
        if lock.exists():
            raise RuntimeError("Protocol already frozen; do not overwrite or tune.")
        # Only training prices are passed to feature/rank fitting.
        prices = pd.read_csv(SOURCE, parse_dates=["Date"]).set_index("Date").Close
        cutoffs = fit_cutoffs(snapshots(prices.loc[:PROTOCOL["training_end"]]))
        lock.write_text(json.dumps(dict(protocol=PROTOCOL, hashes=fingerprint(),
                                        cutoffs=cutoffs), indent=2))
        print("Frozen formula, source, evaluator and training-only ranks. No holdout outcomes evaluated.")
    elif command == "evaluate":
        frozen = json.loads(lock.read_text())
        if frozen["hashes"] != fingerprint() or frozen["protocol"] != PROTOCOL:
            raise RuntimeError("Frozen code or data changed; evaluation refused.")
        if (OUT/"conclusion.json").exists():
            raise RuntimeError("Results already released; reuse them, do not retune.")
        prices = pd.read_csv(SOURCE, parse_dates=["Date"]).set_index("Date").Close
        if str(prices.index[-1].date()) != PROTOCOL["data_end"]:
            raise RuntimeError("Unexpected source end date.")
        features = assign_ranks(snapshots(prices), frozen["cutoffs"])
        summaries, comparisons, records = [], [], []
        for horizon in PROTOCOL["horizons_sessions"]:
            frame = outcomes(prices, features, horizon)
            summary, comparison = summarize(frame, horizon)
            records.append(frame)
            summaries.append(summary)
            comparisons.append(comparison)
        summary = pd.concat(summaries, ignore_index=True)
        comparison = pd.concat(comparisons, ignore_index=True)
        primary = comparison.loc[(comparison.horizon == 21) &
                                 (comparison.group == "k_edge: High") &
                                 (comparison.baseline == "trend: High")].iloc[0]
        passed = bool(primary.return_ci_low > 0 and primary.drawdown_difference_pp >= 0)
        text = (
            "K remains an unvalidated screening heuristic, not a profit probability or proven edge. " +
            ("Primary historical criterion met, but not independent confirmation. " if passed else
             "Primary historical criterion not met. ") +
            "The predeclared 21-session high edge-K versus high trend-only comparison: "
            f"return difference {primary.return_difference_pp:.2f} percentage points; "
            f"{primary.status}. "
            f"Mean drawdown difference {primary.drawdown_difference_pp:.2f} percentage points "
            "(positive means less severe). "
            "No promotion is permitted from this reused historical sample. "
            "Rank ties are kept together, and sparse groups are not evidence of success. "
            "A genuinely untouched holdout and cross-symbol ranking validation remain unavailable."
        )
        for name, data in (("snapshots", features), ("outcomes", pd.concat(records)),
                           ("summary", summary), ("comparisons", comparison)):
            data.to_csv(OUT/f"{name}.csv", index=False)
        conclusion = dict(text=text, status="Unvalidated", freshness=PROTOCOL["freshness"],
                          primary_criterion_met=passed,
                          usable_snapshots=int(features.k_edge.notna().sum()),
                          unavailable_snapshots=int(features.k_edge.isna().sum()))
        (OUT/"conclusion.json").write_text(json.dumps(conclusion, indent=2))
        print(text)
    else:
        raise ValueError("Use freeze or evaluate.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) == 2 else "")
