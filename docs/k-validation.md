# Frozen K historical evaluation

This study does not change the requested K formula, live ranks, daily signal,
or chart controls. K remains an **unvalidated screening heuristic**.

## Predeclared protocol

Run `python scripts/k_validation_report.py freeze` once, then
`python scripts/k_validation_report.py evaluate` once. Freeze records the
source SHA256, model and evaluator hashes, full protocol, and rank cutoffs
calculated only from training features through December 2018. Evaluation
refuses changed code/data or an already released conclusion. Do not delete the
lock to try another rule on these outcomes.

Snapshots are taken every five sessions after 260 closes. Each uses the
requested 252-close R/S estimator, score clamp, independent MA200/60-session
drift, signed K, edge-only K and existing signed labels. Temporal rank
terciles are fixed on training; equal scores stay together, even if a rank is
empty. No threshold is selected by forward returns.

The K-specific test partition starts January 2019. Training forward windows
crossing that boundary are purged. Entry occurs at the next close (not the
close that generated the signal), followed by fixed 5, 21 and 63 session
horizons. Only fully matured windows are included. Returns and worst
peak-to-trough daily-close drawdowns are reported for every rank and signed
label, plus trend-only, reversion-only and unconditional comparisons.

The primary comparison is high edge-K versus high trend-only at 21 sessions,
with a positive lower return-difference confidence bound, no worse average
drawdown, and at least 20 disjoint observations in both groups. All other
comparisons are exploratory. Even passing this primary criterion cannot
validate K on reused data.

Circular paired time-block resampling uses blocks at least as long as the
holding period in snapshot units, 2,000 replicates and a fixed seed. The
same sampled dates are used for each group and baseline. These are
differences between conditional group means, not paired trades or
investable long-short portfolio returns. Non-overlapping results use one
common greedy time grid chosen without outcomes. Sparse intervals are
withheld, not replaced with zero. This handles overlap approximately;
it cannot remove regime dependence or multiple-testing risk.

## Evidence limitations

The source is the existing adjusted SOXL history originally downloaded through
yfinance for the signal study. The end date is October 20, 2026.
The source was already inspected in other research, so this is a held-out
partition for this frozen K experiment, **not a genuinely untouched holdout**.
Historical vintage prices are unavailable. Revised adjustments, ticker
selection, costs, intraday risk and survivorship are not controlled.

Only SOXL is present. These are temporal ranks of that symbol, not evidence
that cross-sectional K rankings select better investments. A future,
unseen sample and a predeclared multi-symbol universe are required before
any promotion claim. Failures, empty labels and uncertainty must remain visible.

The in-app “K historical evidence” section reads the released files only,
and offers a complete ZIP of the frozen protocol, per-snapshot features,
per-window outcomes, summary, baseline comparisons and conclusion.

## Released result

The primary criterion was not met and its comparison could not be estimated:
the high-trend rank is empty because the training upper tercile is already
the maximum trend score (100), while equality remains in the lower bucket.
High edge-K at 21 sessions has 10 overlapping observations and only 2 on the
common non-overlapping grid. Its descriptive mean return is 8.94%, versus
7.98% unconditionally, but that is not reliable evidence of an advantage.
Its mean drawdown is -23.16%, versus -23.19% unconditionally. These are
holding-window averages, not annualized or portfolio performance.
No intervals are reported for that sparse K group. Empty comparisons are
missing values, never zero effects. Neither the tie policy nor thresholds
were adjusted to manufacture a usable primary test.
