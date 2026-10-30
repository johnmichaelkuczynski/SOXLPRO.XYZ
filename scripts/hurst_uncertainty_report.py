"""Reproduce the controlled finite-sample R/S study without market data or APIs."""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from hurst_uncertainty import (
    WINDOWS, REFERENCE, estimator_fingerprint, rs_batch, fractional_gaussian_increments,
)


def run(trials=2000, seed=20261030):
    rows, null_samples = [], {}
    # Separate calibration and evaluation streams, fixed before observing results.
    streams = np.random.SeedSequence(seed).spawn(len(WINDOWS) * 4)
    for index, n in enumerate(WINDOWS):
        null = rs_batch(np.random.default_rng(streams[index*4]).normal(size=(trials, n-1)))
        null_samples[str(n)] = np.sort(null).tolist()
        for j, h in enumerate((.3, .5, .7)):
            rng = np.random.default_rng(streams[index*4+j+1])
            estimates = rs_batch(fractional_gaussian_increments(rng, trials, n, h))
            p = (1 + np.searchsorted(np.sort(null), estimates, side="right")) / (trials + 1)
            flags = (estimates < .5) & (p <= .05)
            rate = float(flags.mean())
            rows.append(dict(
                closes=n, increments=n-1, true_h=h, trials=trials,
                mean=float(estimates.mean()), bias=float(estimates.mean()-h),
                sd=float(estimates.std(ddof=1)),
                rmse=float(np.sqrt(np.mean((estimates-h)**2))),
                sampling_95=np.quantile(estimates, [.025,.975]).tolist(),
                naive_below_half=float((estimates < .5).mean()),
                evidence_rate=rate,
                evidence_rate_mc_se=float(np.sqrt(rate*(1-rate)/trials)),
            ))
    return dict(
        seed=seed, trials_per_cell=trials, estimator_sha256=estimator_fingerprint(),
        protocol="Gaussian fGn H=0.3/0.5/0.7; N closes, N-1 increments; independent null calibration; one-sided p<=0.05 and raw H<0.5.",
        null_samples=null_samples, summary=rows,
    )


def main():
    data = run()
    REFERENCE.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    lines = [
        "# Short-window Hurst uncertainty",
        "",
        f"Seed {data['seed']}; 2,000 independent paths per evaluation cell and 2,000 separate null calibration paths per window.",
        "Windows count closing prices: 100/252/500 closes give 99/251/499 log increments.",
        "Exact Gaussian fractional-noise covariance supplies known H=0.3 (anti-persistent), 0.5 (random walk), and 0.7 (persistent).",
        "R/S uses precisely the production block sizes, ddof=1 and log-scale regression. Simulation operates on increments; their cumulative sums are log prices.",
        "",
        "| Closes | True H | Mean | Bias | SD | RMSE | Central 95% sampling range | H<0.5 | Evidence rate (MC SE) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in data["summary"]:
        low, high = r["sampling_95"]
        lines.append(
            f"| {r['closes']} | {r['true_h']:.1f} | {r['mean']:.3f} | {r['bias']:+.3f} | "
            f"{r['sd']:.3f} | {r['rmse']:.3f} | {low:.3f}–{high:.3f} | "
            f"{r['naive_below_half']:.1%} | {r['evidence_rate']:.1%} ({r['evidence_rate_mc_se']:.1%}) |"
        )
    lines += [
        "",
        "## Interpretation and indicator",
        "Bias is substantial and positive: a raw threshold of 0.5 is not an unbiased random-walk benchmark. Sampling distributions overlap, especially at 100 closes; a low score is not proof of no anti-persistence.",
        "The separate evidence indicator uses p=(1 + number of null estimates <= observed H)/(2,001). It requires p<=0.05 AND raw H<0.5, otherwise reports 'Not distinguished from noise'. This does not establish the null is true or diagnose persistence.",
        "The H=0.5 evidence rate measures independent false positives; H=0.3 measures power at this specific alternative. Monte Carlo SE describes simulation uncertainty in these rates, not investment risk. Independent-null rate need not equal exactly 5%.",
        "The displayed null range is a central sampling range under an iid Gaussian random walk, NOT a confidence interval for the observed asset's true H. Null mean minus 0.5 is finite-sample bias, not a correction applied to the asset.",
        "Only exact supported counts receive evidence: other lookbacks, missing history, constant prices or an outdated reference return explicit N/A. No interpolation or nearest-window substitution.",
        "Score remains clamp((0.5-H)*200,0,100); H, K ranking, trend and price-level half-life remain unchanged. Half-life is a separate price-level regression and neither calibrated nor validated by this study.",
        "",
        "## Limits",
        "Gaussian stationary increments are controlled reference models, not a validation of stock-market reversion or profitable trading. Fat tails, volatility clustering, structural breaks, data quality and multiple selected symbols/windows can invalidate nominal test rates. Results are single-window, not multiplicity-adjusted.",
        "This study does not infer an asset-specific H confidence interval, half-life uncertainty, stationarity, or future returns. Anti-persistence concerns increments, not attraction to a fixed price.",
        "",
        "Reproduce: `OPENBLAS_NUM_THREADS=1 python scripts/hurst_uncertainty_report.py`.",
        "Machine-readable summaries and sorted calibration draws are in reference.json. The estimator source fingerprint prevents silently using stale calibration.",
    ]
    (REFERENCE.parent / "README.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
