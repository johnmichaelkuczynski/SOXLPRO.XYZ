# Historical option probability study

The study is available in Options → Historical probability validation, without a
login or live quote request. No real historical option archive is bundled with
this application. Until a suitable archive has been supplied and audited, there
are no empirical accuracy results. Synthetic test fixtures only test the software.
All live projection probabilities remain experimental and unvalidated.

## CSV data contract

All timestamps must include their real timezone offset (or Z). Numbers use decimal
units, not percentages. Prices are per share, and only standard 100-share SOXL
calls and puts are supported. Supply real historical NBBO snapshots, not daily
option trade OHLC (trade highs/lows are not executable bid/ask observations).
Export from a licensed historical data source; the existing live snapshot
integration does not reconstruct past quotes. Do not fill missing prices or IV
from later observations. The study never fetches data or uses credentials.

Underlying CSV columns:

`timestamp,available_at,Close`

One observation per trading day. `timestamp` is the observation time,
`available_at` is when that value was actually observable. At least 253 usable
positive closes must be available at each forecast. Do not use a currently
back-adjusted history that incorporates later splits/distributions. Use a
corporate-action-free study window with point-in-time observations. Split-spanning
histories and adjusted contracts require a separate, audited point-in-time
corporate-action implementation and are not supported by this study.

Option CSV columns:

`ticker,timestamp,quote_time,spot_time,iv_time,rate_time,dividend_time,expiration,type,strike,spot,iv,bid,ask,rate,dividend,multiplier,source`

`timestamp` is the study cutoff: 16:00 America/New_York on a regular trading
session, with the date's correct DST offset. `quote_time`, `spot_time`, and
`iv_time` are the actual observation/availability times and must be no later than
the cutoff and no more than 15 minutes old. `iv` must be contemporaneous, not
today's IV copied backward. `rate_time` and `dividend_time` identify when those
assumptions were known, and cannot be later than the cutoff. `dividend` is the
then-known annual continuous yield assumption; it is not a realized future yield.
`expiration` is YYYY-MM-DD; `type` is call or put. `multiplier` must be 100;
`source` is a nonempty provenance label. Contract terms cannot change within a
ticker. Only original, unadjusted contracts may be included.

Session CSV columns:

`timestamp`

A sorted, unique list of regular 16:00 NY session cutoffs covering the entire study
window. Obtain this from an independent exchange calendar, not from the available
option rows. Exclude early-close sessions consistently: this version measures
regular-close sampled paths, not all exchange sessions. Include sessions with
missing option quotes so the report can count incomplete paths rather than
silently treating them as complete. Include delisted/expired contracts in the
historical universe; do not select only today's surviving contracts.

## Frozen protocol

Before inspecting outcomes, freeze the input universe, dates, costs and horizons.
The protocol uses expanding historical log-return mean and volatility, annualized
with 252 sessions, matching the live projection model. Every fit filters both
observation and availability timestamps to the entry cutoff. Forecasts use entry
IV, rate and dividend assumptions only; future IV and quotes never enter a fit.
Volatility regimes use fixed annualized realized-volatility thresholds of 50% and
100%. Expiry groups are 1–30, 31–90 and 91–180 days by default.

For each entry, score complete 5-, 10- and 20-regular-session paths ending no later
than expiry. A missing or stale daily quote excludes that horizon and records the
reason. Horizon-end and expiry cutoffs must be in the session manifest. Exits at
expiry use an observed bid before expiration, not an invented intrinsic fill.
The study is a walk-forward out-of-sample audit, not a fitted recalibration of the
live probability. Do not tune the protocol on this report and call a rerun a new
holdout.

Execution buys at ask plus slippage, sells at bid minus slippage, and charges the
per-contract fee on both sides. Forecast liquidation bids subtract the entry
half-spread from modeled fair values, floored at zero before slippage; this is an
explicit spread assumption, not knowledge of future execution. Negative net
liquidation proceeds from costs are possible. Forecast and realized P/L use the
same strict profit threshold (>0). Costs exclude taxes, market impact and funding.

Compare Brier score, clipped log loss, reliability bins and expected calibration
error to a 50% baseline, a zero-log-drift simulation and a Laplace-smoothed profit
frequency using only matching type/horizon outcomes fully closed before entry.
No previous outcomes gives a 50% frequency baseline. Lower Brier/log loss is better.
Baseline comparisons use the same scored observations, not separate samples.
The report also retains the unadjusted, frictionless probability shown by the
live model (using the entry ask as the purchase premium), and scores that
probability against net realized profit separately. The main reliability table
uses the execution-adjusted forecast; these are deliberately distinct.

Daily extreme coverage compares observed daily bid lows/highs to forecast 5th
percentile path lows / 95th percentile path highs. Nominal marginal coverage is
95%, not 90% joint coverage; these are not intraday limits. Both measured and
simulated paths exclude entry and use exactly the same regular-close dates.
Reports include separate expiry, horizon, type and volatility-regime summaries,
and joint expiry/regime/horizon cells. Cells below 30 observations are explicitly
insufficient; even larger cells are only descriptive. Trades overlap. Brier
intervals resample entry-month blocks (500 deterministic draws, at least six
months); long cross-month holdings can retain dependence. These intervals are not
formal calibration acceptance tests.

## American and dividend diagnostics

At entry, compare European price and a 300-step American CRR tree at the same
observed spot/IV and then-known rate/yield, with market midpoint residuals.
Record the exercise premium and European price change from including versus
omitting dividend yield. Positive exercise premium identifies possible material
European underpricing. Midpoint errors are not execution P/L, and IV may itself
be European-implied, making some residual comparisons circular.

The continuous-yield tree does not model actual discrete ex-dividend cash flows,
optimal exercise around those dates, assignment, or corporate actions. A small
tree premium therefore does not establish American-pricing accuracy. Independent
discrete-dividend valuation and historical fill/universe audits are required
before considering any stronger probability claim. No report automatically
changes the experimental labels.

## Reproducibility and limits

The download contains all scored forecasts, actual outcomes, exclusions,
configuration, input SHA-256, strata and limitations. Random seeds are fixed.
The UI limits each CSV to 10 MB and option quotes to 1,000 rows. For larger studies:

`python scripts/validate_options.py --history history.csv --quotes quotes.csv --sessions sessions.csv --output /tmp/options-study.json`

Optional `--fee`, `--slippage`, and `--samples` configure the same runner. Store
large private archives outside version control. Never publish fabricated
fixtures as historical evidence. Data-source labels and checksums support
inspection but do not authenticate provider provenance or universe completeness.
