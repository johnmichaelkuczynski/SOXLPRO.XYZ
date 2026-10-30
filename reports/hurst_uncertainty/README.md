# Short-window Hurst uncertainty

Seed 20261030; 2,000 independent paths per evaluation cell and 2,000 separate null calibration paths per window.
Windows count closing prices: 100/252/500 closes give 99/251/499 log increments.
Exact Gaussian fractional-noise covariance supplies known H=0.3 (anti-persistent), 0.5 (random walk), and 0.7 (persistent).
R/S uses precisely the production block sizes, ddof=1 and log-scale regression. Simulation operates on increments; their cumulative sums are log prices.

| Closes | True H | Mean | Bias | SD | RMSE | Central 95% sampling range | H<0.5 | Evidence rate (MC SE) |
|---|---|---|---|---|---|---|---|---|
| 100 | 0.3 | 0.482 | +0.182 | 0.078 | 0.198 | 0.334–0.638 | 59.7% | 49.8% (1.1%) |
| 100 | 0.5 | 0.624 | +0.124 | 0.088 | 0.152 | 0.457–0.786 | 7.8% | 4.9% (0.5%) |
| 100 | 0.7 | 0.742 | +0.042 | 0.095 | 0.104 | 0.549–0.926 | 0.8% | 0.4% (0.1%) |
| 252 | 0.3 | 0.449 | +0.149 | 0.047 | 0.157 | 0.360–0.543 | 85.5% | 85.5% (0.8%) |
| 252 | 0.5 | 0.597 | +0.097 | 0.058 | 0.113 | 0.482–0.710 | 5.0% | 5.0% (0.5%) |
| 252 | 0.7 | 0.730 | +0.030 | 0.063 | 0.069 | 0.606–0.849 | 0.0% | 0.0% (0.0%) |
| 500 | 0.3 | 0.430 | +0.130 | 0.035 | 0.135 | 0.361–0.497 | 97.9% | 97.9% (0.3%) |
| 500 | 0.5 | 0.583 | +0.083 | 0.043 | 0.094 | 0.496–0.668 | 3.0% | 3.0% (0.4%) |
| 500 | 0.7 | 0.726 | +0.026 | 0.049 | 0.055 | 0.629–0.823 | 0.0% | 0.0% (0.0%) |

## Interpretation and indicator
Bias is substantial and positive: a raw threshold of 0.5 is not an unbiased random-walk benchmark. Sampling distributions overlap, especially at 100 closes; a low score is not proof of no anti-persistence.
The separate evidence indicator uses p=(1 + number of null estimates <= observed H)/(2,001). It requires p<=0.05 AND raw H<0.5, otherwise reports 'Not distinguished from noise'. This does not establish the null is true or diagnose persistence.
The H=0.5 evidence rate measures independent false positives; H=0.3 measures power at this specific alternative. Monte Carlo SE describes simulation uncertainty in these rates, not investment risk. Independent-null rate need not equal exactly 5%.
The displayed null range is a central sampling range under an iid Gaussian random walk, NOT a confidence interval for the observed asset's true H. Null mean minus 0.5 is finite-sample bias, not a correction applied to the asset.
Only exact supported counts receive evidence: other lookbacks, missing history, constant prices or an outdated reference return explicit N/A. No interpolation or nearest-window substitution.
Score remains clamp((0.5-H)*200,0,100); H, K ranking, trend and price-level half-life remain unchanged. Half-life is a separate price-level regression and neither calibrated nor validated by this study.

## Limits
Gaussian stationary increments are controlled reference models, not a validation of stock-market reversion or profitable trading. Fat tails, volatility clustering, structural breaks, data quality and multiple selected symbols/windows can invalidate nominal test rates. Results are single-window, not multiplicity-adjusted.
This study does not infer an asset-specific H confidence interval, half-life uncertainty, stationarity, or future returns. Anti-persistence concerns increments, not attraction to a fixed price.

Reproduce: `OPENBLAS_NUM_THREADS=1 python scripts/hurst_uncertainty_report.py`.
Machine-readable summaries and sorted calibration draws are in reference.json. The estimator source fingerprint prevents silently using stale calibration.
