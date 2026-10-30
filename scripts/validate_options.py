"""Run: python scripts/validate_options.py --help"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from options_validation import StudyConfig, report_json, run_study


def main():
    parser = argparse.ArgumentParser(description="Causal historical options validation; real bid/ask CSVs required.")
    parser.add_argument("--history", required=True)
    parser.add_argument("--quotes", required=True)
    parser.add_argument("--sessions", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--fee", type=float, default=.65)
    parser.add_argument("--slippage", type=float, default=.01)
    parser.add_argument("--samples", type=int, default=2000)
    args = parser.parse_args()
    try:
        report = run_study(pd.read_csv(args.history), pd.read_csv(args.quotes),
                           pd.read_csv(args.sessions)["timestamp"],
                           StudyConfig(fee_per_contract=args.fee,
                                       slippage_per_share=args.slippage, samples=args.samples))
        Path(args.output).write_text(report_json(report))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"Study unavailable: {exc}\n")
    print(report["status"])
    print(f'Scored: {len(report["observations"])}; excluded: {len(report["exclusions"])}')


if __name__ == "__main__":
    main()
