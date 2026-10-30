"""Reproduce the frozen scenario study without modifying daily signal artifacts."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
from price_scenario_validation import PROTOCOL, walk_forward, summarize

OUT = ROOT / "reports/price_scenario_validation"
SOURCE = ROOT / "docs/soxl_signal_study_prices.csv"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = ["price_scenario_model.py", "price_scenario_validation.py", "landing_signal.py"]
    protocol = dict(PROTOCOL, source=str(SOURCE.relative_to(ROOT)),
                    source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                    code_sha256={f: hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files})
    frozen = OUT / "protocol.json"
    if frozen.exists() and json.loads(frozen.read_text()) != protocol:
        raise RuntimeError("Frozen protocol/data/code changed; use a separately identified experiment.")
    # Persist freeze BEFORE reading or evaluating holdout outcomes.
    frozen.write_text(json.dumps(protocol, indent=2) + "\n")
    closes = pd.read_csv(SOURCE, parse_dates=["Date"]).set_index("Date").Close
    predictions = walk_forward(closes)
    summary, calibration = summarize(predictions)
    predictions.to_csv(OUT / "predictions.csv", index=False)
    result = dict(summary=summary, calibration=calibration)
    (OUT / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    lines = [
        "# Hypothetical entry-price validation",
        "",
        "Status: exploratory, NOT validated next-trade probabilities. Daily NO EDGE is unchanged.",
        "Conclusion: no demonstrated forecast advantage. One- and six-month Brier-difference",
        "uncertainty intervals include zero; nominal 80% ranges substantially under-cover realized returns.",
        "Only two supported twelve-month observations are available, so that horizon is inconclusive.",
        "",
        f"Source: {SOURCE.name}, {closes.index[0].date()} through {closes.index[-1].date()}.",
        "Rules and source/code hashes were persisted before this evaluation; no parameters were tuned.",
        "2019 onward is held out from method selection in this study, not previously unseen data across the project.",
        "Older matured holdout outcomes enter later training sets by the predeclared walk-forward rule.",
        "This is a retrospective pseudo-out-of-sample study, not a prospective independent trial.",
        "",
        "Only observed entry closes have observable outcomes. Arbitrary counterfactual slider prices cannot",
        "be validated by relabeling a realized return. This study tests range matching at actual historical",
        "entry prices, not causal effects of buying at a different price on the same date.",
        "The saved adjusted-close snapshot is not a point-in-time vintage; future corporate-action adjustments",
        "may affect absolute dollar eligibility. Fees, slippage and execution at the signal close are not modeled.",
        "",
        "Fixed non-overlapping origin calendars are shared by matched and unconditional forecasts.",
        "Unsupported forecasts are excluded from BOTH sides of paired comparisons, not silently rescheduled.",
        "Pending outcomes are never scored. Unconditional training uses all eligible score-history dates,",
        "without score matching, the same maturity cutoff and earliest-first horizon spacing.",
        "",
        "Brier and 80% interval scores: lower is better. Deltas are matched minus unconditional.",
        "Calibration bias is mean forecast probability minus observed frequency; ideal is zero.",
        "Coverage target is 80%. Wilson intervals are descriptive binomial approximations.",
        "Circular three-origin block-bootstrap 95% intervals allow some serial dependence but are approximate",
        "with few blocks and regime changes; they do not establish independent effective sample sizes.",
        "Intervals are not multiplicity-adjusted across horizons. Fewer than six scored origins suppress bootstrap intervals.",
        "",
    ]
    for row in summary:
        lines += [f"## {row['horizon']} sessions", "", "```json", json.dumps(row, indent=2), "```", ""]
    lines += ["## Calibration by fixed probability bin", "", "```json", json.dumps(calibration, indent=2), "```", "",
              "No stronger claims or changes to the slider/daily trading rule are authorized by this retrospective study.",
              "Reproduce: python scripts/price_scenario_validation_report.py",
              "Audit: protocol.json, predictions.csv and summary.json in this directory."]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
