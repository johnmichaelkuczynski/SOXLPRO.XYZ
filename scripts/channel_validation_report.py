"""Run the separate, fixed walk-forward experiment; never modify signal holdouts."""
from pathlib import Path
import sys
import hashlib
import html
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from area_lab.channel_validation import PROTOCOL, build_windows, walk_forward, summarize

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/soxl_signal_study_prices.csv"
OUT = ROOT / "reports/channel_validation"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # Write the rule specification before looking at outcomes.
    protocol = dict(PROTOCOL, source=str(SOURCE.relative_to(ROOT)),
                    source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest())
    protocol_path = OUT / "protocol.json"
    if protocol_path.exists() and json.loads(protocol_path.read_text()) != protocol:
        raise RuntimeError("Protocol or source changed. Create a separately identified experiment.")
    protocol_path.write_text(json.dumps(protocol, indent=2))
    prices = pd.read_csv(SOURCE, parse_dates=["Date"]).set_index("Date").Close
    windows = build_windows(prices)
    predictions = walk_forward(windows)
    if predictions.empty:
        raise RuntimeError("Insufficient matured training history; no comparison available.")
    summary, calibration = summarize(predictions)
    area_rows = summary[summary.model == "Calibrated lognormal + area"]
    raw_rows = summary[summary.model == "Lognormal"]
    improved = int((area_rows.brier.to_numpy() < raw_rows.brier.to_numpy()).sum())
    positive_intervals = int((area_rows.area_gain_vs_raw_ci_low > 0).sum())
    brier_raw = float(((predictions.hit - predictions.raw_probability)**2).mean())
    brier_area = float(((predictions.hit - predictions.area_probability)**2).mean())
    conclusion = (
        f"No demonstrated area advantage in this experiment. "
        if positive_intervals == 0 else
        "Some historical comparisons favor area; this remains exploratory, not a proven edge. "
    ) + (
        f"{len(predictions):,} matched forecasts on {predictions.origin.nunique()} historical start dates. "
        f"Pooled Brier score: lognormal {brier_raw:.4f}; area-enhanced {brier_area:.4f} "
        f"(lower is better). Area had a lower score in {improved} of {len(area_rows)} "
        f"line/horizon comparisons; {positive_intervals} had an improvement interval wholly above zero. "
        "Long-horizon evidence is thin: only 9 non-overlapping annual windows per line. "
        "Do not use this fixed area rule as a proven trading signal."
    )
    (OUT / "conclusion.json").write_text(json.dumps({"text": conclusion}, indent=2))
    for name, frame in (("windows", windows), ("predictions", predictions),
                        ("summary", summary), ("calibration", calibration)):
        frame.to_csv(OUT / f"{name}.csv", index=False)
    notes = (
        "Exploratory historical research—not proof of a trading edge. Automatic channels are refitted "
        "on the expanding history ending at each forecast date. No current/full-history channel is "
        "projected backward. Both learned models and their scalers use only earlier windows whose "
        "outcomes were fully known by that date. The first 60 matured forecast dates train the models; "
        "early windows without that history are excluded from ALL matched comparisons. "
        "Price targets are fixed at each deadline; a hit is a directional crossing on a later daily "
        "adjusted CLOSE, not an intraday touch or a moving-line crossing. The lognormal model estimates "
        "continuous-path hits, so its comparison with daily-close hits has a sampling limitation. "
        "A 20-session area rectangle is a predeclared research rule, not a backtest of discretionary "
        "mouse-drawn boxes or user-selected channel windows. At a fixed window its area is closely "
        "related to momentum; it is not independent geometric evidence. The calibrated baseline "
        "controls for recalibration alone. Lower Brier score is better; hit rate alone cannot show "
        "probability accuracy. Forecasts overlap; non-overlapping results are shown separately. "
        "The paired block-bootstrap intervals account approximately for overlapping windows, not "
        "all regime dependence, model-selection risk or multiple comparisons. Positive gain means "
        "area has lower squared probability error. These dates have been examined in other studies: "
        "this is not a fresh untouched holdout. No fees, intraday paths or trading profits are tested. "
        "The chart's displayed probability model is not replaced by these exploratory results."
    )
    sections = [f"<h1>Area and channel walk-forward validation</h1>"
                f"<h2>What the results mean</h2><p>{html.escape(conclusion)}</p>"
                f"<h2>Method and limitations</h2><p>{html.escape(notes)}</p>",
                f"<p>Source: {prices.index[0].date()} through {prices.index[-1].date()}. "
                f"{len(predictions)} matched forecasts on {predictions.origin.nunique()} start dates.</p>",
                "<h2>Frozen protocol and source fingerprint</h2><pre>" +
                html.escape(json.dumps(protocol, indent=2)) + "</pre>"]
    for title, frame in (("Matched results", summary), ("Calibration", calibration),
                         ("Every matched forecast and training cutoff", predictions),
                         ("All causal windows, including initial training-only history", windows)):
        sections.append(f"<h2>{title}</h2><div class='table'>" +
                        frame.to_html(index=False, float_format=lambda x: f"{x:.6g}") + "</div>")
    document = ("<!doctype html><html lang='en'><meta charset='utf-8'>"
                "<title>Area and channel validation</title><style>"
                "body{font:15px/1.6 system-ui;margin:24px;color:#172033}"
                ".table{overflow:auto;max-height:650px}table{border-collapse:collapse;font-size:12px}"
                "th,td{padding:7px;border:1px solid #ddd;white-space:nowrap}"
                "th{position:sticky;top:0;background:#eef2f8}pre{white-space:pre-wrap}"
                "</style>" + "".join(sections) + "</html>")
    (OUT / "report.html").write_text(document)
    print(summary[["horizon_sessions", "line", "model", "forecasts", "observed_hit_rate",
                   "mean_predicted_probability", "brier", "nonoverlap_forecasts"]].to_string(index=False))
    print(f"\nReport saved to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
