"""Run freeze and evaluate as distinct commands; never refit on the holdout."""
import argparse
import json
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import yfinance as yf
from daily_signal_scorecard import build_rating_history
from short_term_signal import (
    MANIFEST, TRAIN_END, TEST_END, freeze_training, evaluate_frozen, metrics,
)

PRICES = Path("docs/soxl_signal_study_prices.csv")
OUTPUT = Path("reports/signal_validation")


def save_manifest(value):
    # Missing observations are JSON null, not nonstandard NaN tokens.
    clean = json.loads(json.dumps(value), parse_constant=lambda _: None)
    MANIFEST.write_text(json.dumps(clean, indent=2, allow_nan=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["freeze", "evaluate"])
    args = parser.parse_args()
    if args.stage == "freeze":
        if MANIFEST.exists():
            raise SystemExit("Already frozen. Refusing to overwrite or retune.")
        data = yf.Ticker("SOXL").history(start="2010-03-11", end="2026-10-21",
                                        auto_adjust=True)
        if data.empty:
            raise SystemExit("SOXL history unavailable; no study generated.")
        c = data["Close"]
        c.index = c.index.tz_localize(None)
        PRICES.parent.mkdir(exist_ok=True)
        c.to_csv(PRICES)
        frozen = freeze_training(c.loc[:TRAIN_END])
        save_manifest(frozen)
        print("FROZEN before holdout evaluation:", frozen["rule_text"])
        print("Training:", frozen["training_metrics"])
        return

    c = pd.read_csv(PRICES, index_col=0, parse_dates=True)["Close"]
    frozen = json.loads(MANIFEST.read_text())
    if frozen["evaluated"]:
        raise SystemExit("Holdout already evaluated; refusing repeated evaluation.")
    result = evaluate_frozen(c, frozen)
    result["data_end"] = str(c.index[-1].date())
    save_manifest(result)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    from signal_config import OLD_THRESHOLDS
    rows = []
    for horizon in (21, 63, 126, 252):
        new = build_rating_history(c, horizon)
        old = new.copy()
        # Preserve the old strict-boundary semantics, not the new inclusive buys.
        a, b, d, e = OLD_THRESHOLDS
        p = old["Percentile"]
        old["Rating"] = pd.cut(p, [-float("inf"), a, b, d, e, float("inf")],
                               right=False, labels=["BUY", "POSSIBLE BUY", "DO NOTHING",
                                                    "POSSIBLE SELL", "SELL"]).astype(object)
        old.loc[p.isna(), "Rating"] = "INSUFFICIENT HISTORY"
        old.attrs = new.attrs.copy()
        for version, history in [("Old", old), ("New", new)]:
            for spaced in (False, True):
                for rating in ("BUY", "POSSIBLE BUY"):
                    stats = metrics(history, rating, spaced)
                    rows.append(dict(signal="Long-term", thresholds=version, rating=rating,
                                     months={21:1,63:3,126:6,252:12}[horizon],
                                     sampling="Non-overlapping" if spaced else "Overlapping",
                                     **stats))
    long = pd.DataFrame(rows)
    short = pd.DataFrame([
        dict(period="Training 2010–2018", rule=result["rule_text"], **result["training_metrics"]),
        dict(period="Test 2019–2026", rule=result["rule_text"], **result["test_metrics"]),
    ])
    long.to_csv(OUTPUT / "long_term_comparison.csv", index=False)
    short.to_csv(OUTPUT / "short_term_validation.csv", index=False)
    pd.DataFrame([dict(rule=s["rule"]["id"], **s["metrics"])
                  for s in frozen["training_candidates"]]).to_csv(OUTPUT / "training_candidates.csv", index=False)
    note = (
        f"Data: {c.index[0]:%Y-%m-%d}–{c.index[-1]:%Y-%m-%d}. "
        "Adjusted Yahoo daily closes. Entry at next session close; exit 21/63/126/252 sessions after entry. "
        "Worst dip is the lowest closing return during the holding period, capped at zero. "
        "Non-overlapping uses the existing common calendar schedule, selected before grouping by rating; "
        "baseline uses that same schedule. Overlapping baseline uses every eligible rated day. "
        "Training outcomes crossing 2018-12-31 are excluded; pending outcomes are excluded. "
        "Training windows use pre-2019 observations only. Candidate thresholds were declared before test evaluation. "
        "Only one rule was selected by training lift, preferring at least 20 observations; no Possible Buy rule was fitted. "
        "Test results were not used to pick another rule. If test observations <30 or lift <10 pp, deployment is NO EDGE every day. "
        "No costs, slippage, or intraday lows. Adjusted history is current-vintage, not point-in-time vendor archives. "
        "This is a single frozen holdout, not rolling reoptimization. Any non-overlapping count below 20 is too thin to trust."
    )
    def table(frame):
        display = frame.copy()
        display["Evidence warning"] = display.apply(
            lambda r: "TOO THIN TO TRUST" if r["too_thin"] and r.get("sampling", "Non-overlapping") == "Non-overlapping" else "", axis=1)
        return display.to_html(index=False, float_format=lambda v:f"{v:.2f}", escape=True)
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>SOXL signal validation</title>
    <style>body{{font:14px Arial;margin:30px;color:#172033}}table{{border-collapse:collapse;font-size:12px}}
    td,th{{border:1px solid #ccd3dc;padding:7px;text-align:left}}th{{background:#eaf0f7}}
    .scroll{{overflow:auto}}p{{max-width:1100px;line-height:1.6}}</style></head><body>
    <h1>SOXL signal validation</h1><p>{escape(note)}</p>
    <h2>Short-term acceptance: {'PASS' if result['passed'] else 'FAIL — NO EDGE every day'}</h2>
    <p>{escape(result['rule_text'])}</p><div class="scroll">{table(short)}</div>
    <h2>Long-term old versus new thresholds</h2><p>Old: BUY &lt;15, POSSIBLE BUY 15–&lt;35.
    New: BUY ≤5, POSSIBLE BUY &gt;5–≤15. Sell thresholds unchanged.</p>
    <div class="scroll">{table(long)}</div></body></html>"""
    (OUTPUT / "report.html").write_text(html)
    print(json.dumps(result["test_metrics"], indent=2))
    print("PASS" if result["passed"] else "FAIL — NO EDGE")


if __name__ == "__main__":
    main()
