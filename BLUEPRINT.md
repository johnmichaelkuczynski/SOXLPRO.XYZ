soxl-analysis-platform/
│
├── app.py                                   # MAIN STREAMLIT ENTRY (~1373 lines)
│                                            # Single-page app, 5 top-level tabs declared in one call:
│                                            #   tab_chart, tab_vol, tab_disloc, tab_strategy, tab_backtest
│                                            #     = st.tabs([
│                                            #         "📊 Chart & Probabilities",
│                                            #         "🌊 Vol Surface",
│                                            #         "⚖️ SOXL-QQQ Dislocation",
│                                            #         "🎯 Strategy Builder",
│                                            #         "🔬 Backtest",
│                                            #       ])
│                                            #
│                                            # DATA-FETCH HELPERS (cached 24h via @st.cache_data):
│                                            #   fetch_soxl_data()      - SOXL daily history (yfinance)
│                                            #   fetch_qqq_data()       - QQQ benchmark overlay
│                                            #   fetch_tqqq_data()      - TQQQ (3× QQQ) overlay
│                                            #   fetch_tlt_data()       - TLT (long-bond) overlay
│                                            #   fetch_xlu_data()       - XLU (utilities) overlay
│                                            #   fetch_vix_data()       - VIX (vol regime) overlay
│                                            #   fetch_short_interest() - FINRA biweekly short interest
│                                            #   fetch_short_volume_history(symbol, days_back) - FINRA daily short volume
│                                            #     - parallel HTTP via ThreadPoolExecutor; 365-day window default
│                                            #
│                                            # UNIT HELPERS:
│                                            #   convert_to_trading_days(value, unit)  - "days/weeks/months/years" → trading days
│                                            #   convert_to_timedelta(value, unit)     - same, but pandas Timedelta
│                                            #   get_price_at_offset(df, days_ago)     - tolerant lookup with weekend skipping
│                                            #
│                                            # TAB BLOCKS (rendered inline, no separate render_* functions for these):
│                                            #
│                                            # tab_chart (lines ~247–1300):
│                                            #   - SOXL log-scale Plotly chart 2010→present, x-axis extended +5y future
│                                            #   - Benchmark overlay toggles (QQQ orange, TQQQ purple, TLT teal,
│                                            #     XLU red, VIX gold dotted) all on same log-y axis
│                                            #   - Custom Streamlit chart component embed for drag-to-draw trend lines
│                                            #     (components/chart_draw/index.html, ~637 lines)
│                                            #   - Period Analysis sub-block (~line 443): "SOXL Patterns" + "Benchmark-Based"
│                                            #     modes; supports QQQ/TLT/XLU/VIX as benchmarks; analogue count per horizon
│                                            #   - Short Interest sub-block (~lines 779–870): biweekly FINRA + daily short-volume
│                                            #   - Probability Engine sub-block (~line 874): magnitude × horizon historical frequency
│                                            #     with configurable lookback window; includes "Benchmark History" predictive mode
│                                            #
│                                            # tab_vol         → calls vol_surface.render_vol_surface_tab()
│                                            # tab_disloc      → calls dislocation.render_dislocation_tab()
│                                            # tab_strategy    → AI Strategy Builder (chat UI; calls strategy_builder)
│                                            # tab_backtest    → calls backtest_ui.render_backtest_tab()
│                                            #
│                                            # NOTE: Earlier prototype "Strategy Builder" UI block sits at top-level
│                                            # tab_strategy AND a richer copy is also wired into the Backtest sub-tab.
│
├── backtest_engine.py                       # PURE MATH / SIMULATION LAYER (~796 lines)
│                                            # No Streamlit imports. Returns plain DataFrames / dicts so each
│                                            # function is independently unit-testable.
│                                            # ─────────────────────────────────────────────────────────────
│                                            # CONSTANTS:
│                                            #   TRADING_DAYS = 252
│                                            #   ALLOCATION_DEFAULTS = { floor, ceiling, sensitivity,
│                                            #                           bear_multiplier, bear_drawdown,
│                                            #                           bear_lookback_frac }
│                                            #     - ALLOCATION_HARD_FLOOR  = 0.02
│                                            #     - ALLOCATION_HARD_CEILING = 0.98
│                                            #   CALL_SLEEVE_DEFAULTS = { sleeve_pct=0.20, days_to_expiry=45,
│                                            #                            roll_at_dte=10, moneyness=1.00,
│                                            #                            vol_window=30, min_sigma=0.20,
│                                            #                            max_sigma=2.00 }
│                                            #   DISCLAIMER (string used in every download report)
│                                            #
│                                            # OPTIONS PRICING (no scipy):
│                                            #   _norm_cdf(x)                          - standard normal CDF via math.erf
│                                            #   _bs_call_price(S, K, T, sigma, r=0)   - Black-Scholes call premium
│                                            #     - Returns intrinsic when T<=0 or sigma<=0 (boundary safe)
│                                            #
│                                            # EQUITY CURVES:
│                                            #   equity_curve_from_returns(returns)    - (1 + r).cumprod()
│                                            #   buy_and_hold_curve(price_series)      - normalized price/price[0]
│                                            #
│                                            # DEVIATION ENGINE (signal generator, used by both legacy and call-sleeve sims):
│                                            #   soxl_allocation_engine(soxl, qqq, **ALLOCATION_DEFAULTS) → DataFrame
│                                            #     columns: { soxl_norm, qqq_norm, deviation, raw_allocation,
│                                            #                regime_mult, allocation }
│                                            #     - SOXL/QQQ normalized to 1.00 at window start
│                                            #     - deviation = soxl_norm − qqq_norm
│                                            #     - raw_allocation = 0.5 + 0.5 × tanh(−sensitivity × dev / dev_scale)
│                                            #     - dev_scale = expanding mean of |deviation| (self-calibrating)
│                                            #     - regime_mult = bear_multiplier when QQQ below rolling-max by bear_drawdown
│                                            #     - allocation = clip(raw_allocation × regime_mult, floor, ceiling)
│                                            #     - Always returns a non-empty frame (1-row synthetic for empty inputs)
│                                            #
│                                            # LEGACY SIMULATOR (kept for backward compat, NOT the default UI strategy):
│                                            #   simulate_allocation_engine(soxl, qqq, **kwargs) → (equity, daily_rets, alloc_df)
│                                            #     - Applies continuous spot-SOXL allocation to daily returns
│                                            #     - Lags allocation by 1 bar (no look-ahead)
│                                            #
│                                            # CALL-SLEEVE SIMULATOR (CURRENT DEFAULT — the one wired into Backtest sub-tab[0]):
│                                            #   simulate_call_sleeve_engine(soxl, qqq, sleeve_pct, days_to_expiry,
│                                            #                               roll_at_dte, moneyness, vol_window,
│                                            #                               min_sigma, max_sigma, floor, ceiling,
│                                            #                               sensitivity, bear_multiplier, bear_drawdown,
│                                            #                               bear_lookback_frac) → dict
│                                            #     returns: {
│                                            #       equity_strategy       - growth of $1 (cash + sleeve mtm)
│                                            #       equity_soxl_bh        - SOXL B&H baseline (growth of $1)
│                                            #       equity_qqq_bh         - QQQ B&H baseline (growth of $1)
│                                            #       sleeve_value          - $ value of call sleeve over time
│                                            #       cash_value            - $ cash over time
│                                            #       sleeve_alloc_target   - target sleeve fill % within the sleeve allowance
│                                            #       sleeve_alloc_actual   - actual sleeve % of total portfolio (mtm)
│                                            #       realized_vol          - σ used for BS pricing (trailing realized, clipped)
│                                            #       contracts_history     - share-equivalent contracts held (/ 100 for display)
│                                            #       roll_events           - list of timestamps where rolls happened
│                                            #       alloc_df              - full deviation/allocation panel
│                                            #       sleeve_pct            - capital at risk (echoed for downstream use)
│                                            #     }
│                                            #     KEY MODELING RULES:
│                                            #     • 1-bar lagged allocation signal: alloc_df["allocation"].iloc[max(i-1,0)]
│                                            #     • Trailing realized vol pricing (rv_window auto-clipped to len/2)
│                                            #       sigma is clipped to [min_sigma, max_sigma]
│                                            #     • Roll trigger: DTE ≤ roll_at_dte OR mtm ≤ 1e-6 → liquidate to cash, open fresh
│                                            #     • ASYMMETRIC RESIZE (critical):
│                                            #         - No position → open fresh to target sleeve $
│                                            #         - Position present, target < current → sell DOWN to target (release cash)
│                                            #         - Position present, target ≥ current → HOLD (never refill decaying premium
│                                            #           mid-cycle; next roll re-sizes up)
│                                            #     • Never refuses: empty/None/non-overlapping/1-bar windows return trivial frames
│                                            #
│                                            # RISK METRICS (REQUIRED PANEL — always rendered by UI):
│                                            #   compute_risk_metrics(equity, label, capital_at_risk=1.0) → dict
│                                            #     keys: Series, Total Return %, CAGR %, Vol (ann) %, Max Drawdown %,
│                                            #           Sharpe, Sortino, Calmar, Capital at Risk %, Return / At-Risk %
│                                            #     - Returns valid zero-filled row when len(equity) < 2 (so the table
│                                            #       always renders, per the spec's "never refuse" rule)
│                                            #
│                                            # LEGACY STATS (used by older sub-tabs):
│                                            #   compute_stats(equity, returns=None, n_trades=None) → dict
│                                            #   random_entry_baseline(price_series, n_trades, holding_days, seed=42)
│                                            #   calibration_curve(predicted_probs, realized_outcomes, n_bins=10)
│                                            #
│                                            # CHART HELPERS:
│                                            #   render_equity_chart(curves, title)
│                                            #   render_calibration_chart(predicted_probs, realized_outcomes, n_bins)
│                                            #
│                                            # REPORT EXPORT (used by every backtest sub-tab via _render_download_buttons):
│                                            #   _stats_rows_to_table(stats_rows)
│                                            #   build_report_text(title, params, methodology, stats_rows, date_range)
│                                            #   build_report_csv(stats_rows)
│                                            #   build_report_docx(title, params, methodology, stats_rows, date_range)
│                                            #   build_report_pdf(title, params, methodology, stats_rows, date_range)
│                                            #   safe_filename(title)
│
├── backtest_ui.py                           # BACKTEST TAB UI (~1437 lines, ALL Streamlit)
│                                            # Entry: render_backtest_tab() — called from app.py tab_backtest.
│                                            # ─────────────────────────────────────────────────────────────
│                                            # SUB-TAB LAYOUT (8 sub-tabs, default index = 0):
│                                            #   sub = st.tabs([
│                                            #     "🎯 Allocation Engine (DEFAULT)",
│                                            #     "Period Analysis",
│                                            #     "Probability Engine",
│                                            #     "Vol Regime",
│                                            #     "SOXL-QQQ Dislocation",
│                                            #     "Strategy Builder",
│                                            #     "Vol Surface (limited)",
│                                            #     "🛠 Custom Strategy",
│                                            #   ])
│                                            #
│                                            # SHARED PRIVATE HELPERS:
│                                            #   _date_range_picker(key_prefix, max_years)             - constrained picker
│                                            #   _permissive_date_range_picker(key_prefix, max_years)  - "never refuse" version
│                                            #   _slice(df, start, end)                                - inclusive date slice
│                                            #   _load_equities(start, end)                            - SOXL+QQQ in one call
│                                            #   _render_results(strategy_eq, soxl_df, qqq_df, ...)    - generic results panel
│                                            #   _render_download_buttons(title, params, methodology, stats_rows,
│                                            #                            date_range, key_suffix)      - 4-format downloads
│                                            #
│                                            # ─────── SUB-TAB IMPLEMENTATIONS ───────
│                                            #
│                                            # _allocation_engine_tab()                                # DEFAULT (sub[0])
│                                            #   Spec-anchored UI for simulate_call_sleeve_engine.
│                                            #   - Description caption: 20%/80% capital structure summary
│                                            #   - Expander 1 "Sleeve & options parameters" (sliders):
│                                            #       sleeve_pct, dte, roll_dte, moneyness, vol_w
│                                            #   - Expander 2 "Sleeve sizing — deviation engine":
│                                            #       floor, ceiling, sensitivity, bear_mult, bear_dd, bear_lb
│                                            #   - Floor < ceiling guard with fallback to defaults
│                                            #   - "Run allocation engine" button → simulate_call_sleeve_engine(...)
│                                            #   - Headline ENGINE RECOMMENDATION card (HTML, custom CSS):
│                                            #       sleeve fill %, calls % of notional, deviation, regime badge,
│                                            #       cash % of notional
│                                            #   - 3-row Plotly chart via _render_allocation_chart() + 3 equity traces
│                                            #     (Strategy, SOXL B&H, QQQ B&H) + actual sleeve fill (mtm) on row 3
│                                            #   - Risk-Adjusted Metrics dataframe (ALWAYS rendered, even on 1-bar windows)
│                                            #     - compute_risk_metrics × 3 (Engine / SOXL B&H / QQQ B&H)
│                                            #   - 4 metric cards: Strategy total return, SOXL B&H total return,
│                                            #     Strategy return / sleeve%-at-risk, Capital efficiency vs SOXL
│                                            #   - "Sleeve & position diagnostics" expander: avg sleeve %, roll events,
│                                            #     avg σ, full daily history (Cash $, Sleeve $, Total $, Target / Actual
│                                            #     sleeve fill %, σ, Contracts)
│                                            #   - "Deviation / allocation panel" expander: every-bar table
│                                            #   - 4-format downloads (TXT/CSV/Word/PDF) with implementation-faithful
│                                            #     methodology string (describes asymmetric resize, not full daily refit)
│                                            #
│                                            # _period_analysis_tab()                                  # sub[1]
│                                            #   Window-based backtest: choose start/end, holding horizon; reports
│                                            #   per-horizon analogue count + outcome distribution.
│                                            #
│                                            # _probability_engine_tab()                               # sub[2]
│                                            #   P(move ≥ M% within H days) over a configurable historical lookback.
│                                            #   Reports n (sample size) alongside every probability.
│                                            #
│                                            # _vol_regime_tab()                                       # sub[3]
│                                            #   Classifies current vol regime as CHEAP / MID-RANGE / EXPENSIVE
│                                            #   using IV / realized-vol percentile bands.
│                                            #
│                                            # _dislocation_tab()                                      # sub[4]
│                                            #   Backtest wrapper around dislocation.py signals (Z-scored residual).
│                                            #
│                                            # _strategy_builder_tab()                                 # sub[5]
│                                            #   Chat-driven AI strategy builder (calls strategy_builder.generate_strategy).
│                                            #   See _render_strategy_chat() helper.
│                                            #
│                                            # _vol_surface_tab()                                      # sub[6]
│                                            #   Backtest entry-points keyed off vol_surface.py BUY/SELL signals.
│                                            #
│                                            # _custom_strategy_tab()                                  # sub[7]
│                                            #   Composable indicator/operator strategy builder. See helpers below.
│                                            #
│                                            # ─────── CUSTOM-STRATEGY HELPERS (sub[7] support) ───────
│                                            #   _default_condition()                                  - one rule template
│                                            #   _default_panel()                                      - entry/exit panel
│                                            #   _init_cs_state()                                      - st.session_state setup
│                                            #   _render_condition_row(panel_key, idx)                 - one AND-row builder
│                                            #   _render_panel(panel_key, label)                       - full panel (AND/OR)
│                                            #
│                                            # ─────── ALLOCATION ENGINE PRIVATE CHART HELPER ───────
│                                            #   _render_allocation_chart(alloc_df, soxl_prices, floor, ceiling)
│                                            #     - 3-row subplot: equity row (filled by caller), normalized SOXL+QQQ
│                                            #       baseline row, sleeve fill % row with floor/ceiling guide lines.
│                                            #
│                                            # ─────── AI CHAT HELPER ───────
│                                            #   _render_strategy_chat()                               - shared chat block
│                                            #     used by both _strategy_builder_tab() and the natural-language
│                                            #     custom-strategy refinement flow.
│
├── strategy_builder.py                      # AI STRATEGY GENERATION (Anthropic, ~537 lines)
│                                            # Used by the top-level tab_strategy AND backtest sub-tab[5].
│                                            # ─────────────────────────────────────────────────────────────
│                                            # CLIENT:
│                                            #   get_client() - returns Anthropic client wired through Replit AI
│                                            #     Integrations env vars:
│                                            #       AI_INTEGRATIONS_ANTHROPIC_BASE_URL
│                                            #       AI_INTEGRATIONS_ANTHROPIC_API_KEY
│                                            #     No user-supplied API key required; uses Replit credits.
│                                            #
│                                            # HELPERS:
│                                            #   esc(text)                                             - HTML escape
│                                            #   compute_probability_table(close_prices, horizons_days, magnitudes)
│                                            #     - Returns 2-D table of P(|move| ≥ M within H days) using rolling
│                                            #       returns over the full provided price history.
│                                            #   compute_stats_summary(close_prices)
│                                            #     - Returns dict with realized vol, max DD, current drawdown,
│                                            #       SOXL position percentile, recent return summary.
│                                            #
│                                            # MAIN ENTRY:
│                                            #   generate_strategy(messages, close_prices) → str (Claude response)
│                                            #     - Builds rich system prompt that includes:
│                                            #         * full computed probability table
│                                            #         * stats summary (current state of SOXL)
│                                            #         * strict JSON output schema (tranched buy ladder + rules)
│                                            #     - Streams Claude's response; returns concatenated text.
│                                            #
│                                            # PARSE + RENDER:
│                                            #   parse_strategy_json(text) → dict | None
│                                            #     - Tolerant parser: handles ```json fences, leading/trailing prose,
│                                            #       and multiple-object responses (picks the largest valid JSON).
│                                            #   render_strategy_html(strategy) → HTML string
│                                            #     - Renders the parsed strategy as styled HTML tables:
│                                            #         summary card, tranched buy ladder, operating rules,
│                                            #         statistical basis, risk notes.
│
├── strategy_nl.py                           # NATURAL-LANGUAGE CUSTOM STRATEGY REFINER (~258 lines)
│                                            # Bridges plain-English descriptions ↔ structured custom_strategy JSON.
│                                            # ─────────────────────────────────────────────────────────────
│                                            # CLIENT:
│                                            #   get_client() - same Anthropic-via-Replit setup as strategy_builder
│                                            #
│                                            # PROMPT BUILDERS:
│                                            #   _indicator_catalog_text() - prose listing of every valid indicator
│                                            #     name and parameter so the LLM can only emit legal rule combinations
│                                            #     (mirrors custom_strategy.ALL_INDICATORS exactly).
│                                            #
│                                            # CHAT LOOP:
│                                            #   chat_refine(messages) → str
│                                            #     - Sends multi-turn conversation to Claude; returns response that
│                                            #       includes a fenced JSON block matching the custom-strategy schema.
│                                            #
│                                            # JSON HANDLING:
│                                            #   extract_strategy_json(text) → dict | None
│                                            #   _validate_side(side)         - "long"/"short" guard
│                                            #   _normalize_side(side)        - canonicalize before storing
│                                            #   _normalize_panel(panel)      - rewrites conditions to canonical form
│                                            #   normalize_strategy(data)     - full top-level cleanup, returns
│                                            #     a dict that custom_strategy.simulate_custom_strategy can consume.
│                                            #   uses_options_signals(cfg)    - bool: does this strategy depend on
│                                            #     vol-surface signals? (gates a UI warning about start-date limits)
│
├── custom_strategy.py                       # COMPOSABLE INDICATOR/OPERATOR ENGINE (~512 lines)
│                                            # Pure math; no Streamlit imports. Drives backtest sub[7].
│                                            # ─────────────────────────────────────────────────────────────
│                                            # CATALOG CONSTANTS (the source of truth for the rule builder):
│                                            #   SIGNAL_VERSION = "1.0"      - bump when computation logic changes
│                                            #   APP_SIGNALS_CATEGORICAL = {
│                                            #     "Vol Surface Signal (Calls)": ["BUY","SELL","NEUTRAL"],
│                                            #     "Vol Surface Signal (Puts)" : ["BUY","SELL","NEUTRAL"],
│                                            #     "Vol Regime Label"          : ["CHEAP","MID-RANGE","EXPENSIVE"],
│                                            #   }
│                                            #   APP_SIGNALS_NUMERIC_ONE_PARAM = {"Period Analysis Percentile(N)"}
│                                            #   APP_SIGNALS_NUMERIC_TWO_PARAM = {"Probability Engine P(M%, Hd)"}
│                                            #   NEEDS_OPTIONS_DATA            = {"Vol Surface Signal (Calls)",
│                                            #                                    "Vol Surface Signal (Puts)"}
│                                            #   OPTIONS_WINDOW_START = "2022-01-01"  - earliest viable date for
│                                            #                                          options-derived signals
│                                            #   INDICATORS_NEEDS_N   - SMA/EMA/RSI/Bollinger/N-day stats/ATR/z-score/...
│                                            #   INDICATORS_NO_N      - SOXL/QQQ/VIX price, MACD, drawdown, ratio,
│                                            #                          days-held, plus categorical APP_SIGNALS
│                                            #   ALL_INDICATORS       - union, sorted (alphabetical) — single source for UI
│                                            #   DEFAULT_N / DEFAULT_N2 - default parameter values per indicator
│                                            #   OPERATORS = [">", "<", "=", "crosses above", "crosses below"]
│                                            #
│                                            # PERSISTENCE:
│                                            #   SAVE_PATH = ".local/saved_strategies.json"
│                                            #   load_all_strategies() / save_strategy(name, config) /
│                                            #     delete_strategy(name) / _ensure_dir()
│                                            #
│                                            # SIGNAL COMPUTATION (point-in-time, no lookahead):
│                                            #   compute_vol_regime_pit(soxl, lookback=252, low_pct=33, high_pct=67)
│                                            #   compute_vol_surface_signal_pit(vix, soxl, side="calls", lookback=252, ...)
│                                            #   compute_probability_pit(soxl, M_pct, H_days, train_window=504)
│                                            #   compute_period_pctile_pit(soxl, N)
│                                            #   compute_indicator(name, n, soxl, qqq, vix, n2=None)
│                                            #     - Dispatches by indicator name; returns a pd.Series aligned to soxl.
│                                            #
│                                            # PANEL EVALUATION:
│                                            #   _series_for_side(side, soxl, qqq, vix, days_held_series)
│                                            #   _condition_signal(cond, soxl, qqq, vix, days_held_series)
│                                            #     - Resolves one {indicator, n, operator, threshold} row → bool Series
│                                            #   evaluate_panel(panel, soxl, qqq, vix, days_held_series)
│                                            #     - Combines conditions with AND-within-row / OR-across-rows.
│                                            #   _eval_at(panel, soxl, qqq, vix, i, days_held_series, precomputed)
│                                            #     - Per-bar evaluator (used inside simulate loop).
│                                            #   panel_uses_options_signals(panel)
│                                            #   panel_uses_days_held(panel)
│                                            #   is_categorical_signal(name)
│                                            #
│                                            # MAIN SIMULATOR:
│                                            #   simulate_custom_strategy(soxl, qqq, vix, entry_panel, exit_panel,
│                                            #                            controls) → result dict
│                                            #     - Long-only; controls: starting_cash, slippage_bps, commission_per_trade,
│                                            #       allow_pyramid, max_hold_days, etc.
│                                            #     - Days-held tracking so "Days held in position" indicator works.
│                                            #     - Returns equity curve + trade log + summary stats.
│                                            #
│                                            # UI-FACING HELPERS:
│                                            #   strategy_uses_app_signals(config) - bool gating
│                                            #   describe_panel(panel)              - human-readable summary string
│
├── vol_surface.py                           # VOL SURFACE + IV-RANK ANALYTICS (~740 lines)
│                                            # Entry: render_vol_surface_tab() — called from app.py tab_vol.
│                                            # ─────────────────────────────────────────────────────────────
│                                            # CONSTANTS:
│                                            #   RISK_FREE_RATE = 0.045
│                                            #
│                                            # PRICING + IV INVERSION (no scipy):
│                                            #   _compute_iv_fallback(mid, spot, strike, t_years, flag)
│                                            #     - Bisection-based IV inversion used when the Polygon Greeks
│                                            #       row is missing or implausible.
│                                            #   _bs_model_price(spot, strike, t_years, vol, flag) - sanity reprice
│                                            #
│                                            # DATA INGEST:
│                                            #   fetch_options_chain(ticker="SOXL", spread_cap=0.25, min_oi=50, min_vol=1)
│                                            #     - Polygon snapshot via data_providers.get_options_snapshot;
│                                            #       filters illiquid contracts (wide spreads, low OI/volume);
│                                            #       backfills missing IV via _compute_iv_fallback.
│                                            #
│                                            # CLEANUP / FILTERS:
│                                            #   apply_no_arb_filters(df) - drops obvious arbitrage violations
│                                            #   fit_per_expiry_spline(df) - cubic spline fit per expiry slice
│                                            #   filter_local_outliers(df, k=5, lo=0.5, hi=2.0)
│                                            #   filter_otm_blend(df) - OTM-only blend for clean smile/skew
│                                            #
│                                            # EXPIRY HELPERS:
│                                            #   next_monthly_opex(today=None) - next 3rd-Friday standard expiry
│                                            #   build_surface_grid(df) - returns (money_grid, days_grid, iv_grid)
│                                            #   atm_iv_for_dte(df, target_dte, tol_money=0.05, tol_dte=15)
│                                            #   skew_25d(df, target_dte=30, tol_dte=15) - 25-delta risk reversal
│                                            #
│                                            # SIGNAL GENERATION (BUY / SELL discrepancy):
│                                            #   detect_anomalies(df_fitted, residual_thresh=0.05, spot=None)
│                                            #     - Flags contracts where market IV diverges from fitted surface
│                                            #       by more than residual_thresh. Splits into BUY (cheap) / SELL (rich).
│                                            #   _kind_label(kind), _process_kind(df_kind) - rendering helpers
│                                            #
│                                            # IV-RANK PANEL:
│                                            #   compute_iv_rank_panel(ticker="SOXL")
│                                            #     - Returns dict { iv_rank, iv_percentile, atm_iv30, realized_vol, ... }
│                                            #     - Drives the CHEAP / MID-RANGE / EXPENSIVE classification used
│                                            #       elsewhere in the app (Vol Regime tab, custom-strategy signals).
│                                            #   render_iv_rank_panel(rv_info, atm_iv30) - HTML/Streamlit panel
│                                            #
│                                            # FIGURES + TABLES:
│                                            #   render_surface_figure(grid_money, grid_days, iv_grid, spot, title)
│                                            #     - 3D Plotly surface (moneyness × DTE × IV)
│                                            #   render_signals_table(df_signals, side) - styled BUY or SELL table
│                                            #
│                                            # ENTRY:
│                                            #   render_vol_surface_tab() - full tab layout (fetch → fit → signals →
│                                            #     IV rank → 3D surface → tables). Caches expensive steps via
│                                            #     st.cache_data at the data_providers layer.
│
├── dislocation.py                           # SOXL-QQQ DISLOCATION ENGINE (~440 lines)
│                                            # Entry: render_dislocation_tab() — called from app.py tab_disloc.
│                                            # ─────────────────────────────────────────────────────────────
│                                            # CONSTANTS:
│                                            #   BETA_LOOKBACKS    = [5, 10, 20, 60, 120]   - multi-horizon rolling β
│                                            #   RESIDUAL_WINDOWS  = [1, 5, 10, 20]         - residual smoothing
│                                            #   STRUCTURAL_BETA   = 3.3                    - SOXL=3× leveraged baseline
│                                            #
│                                            # CORE PIPELINE:
│                                            #   fetch_aligned_prices(years=3) - SOXL + QQQ inner-joined on dates
│                                            #   compute_rolling_betas(df, windows=BETA_LOOKBACKS)
│                                            #     - Rolling OLS β of SOXL_ret on QQQ_ret per window
│                                            #   compute_residuals(df, betas)
│                                            #     - resid_b{w} = SOXL_ret − β_w × QQQ_ret  (for each w in BETA_LOOKBACKS)
│                                            #   compute_zscores(residuals, lookback_days=252)
│                                            #     - Standardized residuals → Z surface (lookback × beta_window matrix)
│                                            #   compute_reversion_table(residuals_df, beta_window=20, resid_window=20, ...)
│                                            #     - Conditional reversion stats: given Z bucket today, what was the
│                                            #       avg next-N-day SOXL move historically?
│                                            #
│                                            # VERDICT:
│                                            #   _classify(z) - bucket: "RICH", "STRETCH-RICH", "FAIR", "STRETCH-CHEAP", "CHEAP"
│                                            #   _render_verdict_card(verdict, color, emoji, message, z, sub) - HTML card
│                                            #
│                                            # FIGURE:
│                                            #   _render_z_surface_3d(matrix_df) - 3D Plotly surface (lookback × β-window × Z)
│                                            #
│                                            # ENTRY:
│                                            #   render_dislocation_tab() - full tab: prices → betas → residuals → Z surface
│                                            #     → verdict card → reversion table → raw data layer (expander).
│                                            #
│                                            # DATA-LAYER (debug expander):
│                                            #   _render_data_layer(df, betas, residuals, matrix, events, lookup)
│
├── data_providers.py                        # MARKET-DATA WRAPPERS (~99 lines)
│                                            # Single source of truth for EODHD + Polygon access. All wrapped in
│                                            # @st.cache_data(ttl=86400) so the rest of the app never re-fetches.
│                                            # ─────────────────────────────────────────────────────────────
│                                            # ENV VARS (read at import):
│                                            #   EODHD_API_KEY       - equity history (EODHD)
│                                            #   POLYGON_API_KEY     - options chain + history (Polygon)
│                                            #
│                                            # CONSTANTS:
│                                            #   EQUITY_MAX_YEARS  = 16       - SOXL history depth
│                                            #   OPTIONS_MAX_YEARS = 4        - options history cap (Polygon plan)
│                                            #
│                                            # API:
│                                            #   get_equity_history(symbol="SOXL", years, suffix=".US") → DataFrame
│                                            #     columns: open, high, low, close, adj_close, volume, ret, log_ret
│                                            #   get_options_snapshot(symbol="SOXL", limit=250) → DataFrame
│                                            #     - Paginates Polygon /v3/snapshot/options; one row per live contract
│                                            #   get_option_history(option_ticker, from_date, to_date) → DataFrame
│                                            #   options_max_start_date() / equity_max_start_date() - date floors
│                                            #     used by UI date pickers.
│
├── components/
│   └── chart_draw/
│       └── index.html                       # CUSTOM STREAMLIT COMPONENT (~637 lines)
│                                            # Bidirectional iframe component embedded via st.components.v1.html.
│                                            # ─────────────────────────────────────────────────────────────
│                                            # - Renders a Plotly chart with a transparent overlay <div> that captures
│                                            #   mousedown/mousemove/mouseup without Plotly hijacking the events.
│                                            # - Implements pixel ↔ data conversion that respects the log-scale y-axis.
│                                            # - Draws drag-to-create trend lines; lines auto-extend forward (dashed
│                                            #   projection up to 5y into the future) and backward (dashed history).
│                                            # - Posts the resulting trend-line coordinates back to Streamlit via
│                                            #   Streamlit.setComponentValue() so app.py can re-render with the line state.
│
├── main.py                                  # NOOP ENTRY (6 lines)
│                                            # def main(): print("Hello from repl-nix-workspace!")
│                                            # Not used in production — the real entry is `streamlit run app.py`.
│
├── attached_assets/                         # USER-UPLOADED ARTIFACTS (screenshots, reference images, txt blueprints)
│                                            # - Not served by the web server.
│                                            # - Includes design references (image_*.png) and the model blueprint
│                                            #   used to seed THIS document.
│
├── .streamlit/
│   └── config.toml                          # Streamlit runtime config
│                                            #   [server]   headless=true, port=5000, address=0.0.0.0,
│                                            #              CORS+XSRF+WebsocketCompression disabled
│                                            #   [browser]  gatherUsageStats=false
│                                            #   [theme]    base=light, primaryColor=#4A90D9,
│                                            #              backgroundColor=#F0F4FA, secondaryBackgroundColor=#FFFFFF,
│                                            #              textColor=#1a1a2e
│
├── .replit                                  # Replit run config (workflow: "Start application" →
│                                            # `streamlit run app.py --server.port 5000`)
├── pyproject.toml                           # Project metadata + Python deps (streamlit, plotly, pandas, numpy,
│                                            # yfinance, requests, anthropic, python-docx, reportlab, python-dateutil)
├── uv.lock                                  # uv lockfile (resolved versions for reproducible installs)
├── replit.md                                # Project overview + user preferences (read by Agent on every session)
├── README.md                                # User-facing README (Overview / Who It's For / Core Capabilities /
│                                            # What Makes It Different / Tech Stack / Project Structure / Running)
└── BLUEPRINT.md                             # THIS FILE — full file-tree blueprint for AI fine-tuning


═══════════════════════════════════════════════════════════════════════════════
ARCHITECTURAL CONVENTIONS (READ BEFORE EDITING)
═══════════════════════════════════════════════════════════════════════════════

1. UI ↔ MATH SEPARATION
   - backtest_engine.py, custom_strategy.py, dislocation.py (compute layer),
     strategy_builder.py, strategy_nl.py, vol_surface.py (compute helpers),
     data_providers.py: NO Streamlit imports in pure-math functions.
   - All st.* calls live in app.py, backtest_ui.py, and the render_* entry
     points (render_vol_surface_tab, render_dislocation_tab).
   - Simulation functions return plain DataFrames / dicts so they are
     independently unit-testable from the shell.

2. NEVER REFUSE
   - The Allocation Engine, Probability Engine, and Custom Strategy simulator
     all return valid (possibly trivial) results for empty / 1-bar / non-
     overlapping windows. They never raise to short-circuit the UI.
   - compute_risk_metrics returns a zero-filled valid row when input is too
     short, so the risk-metrics dataframe always renders.

3. NO LOOK-AHEAD
   - simulate_call_sleeve_engine lags the allocation signal one bar:
       target_alloc = alloc_df["allocation"].iloc[max(i - 1, 0)]
   - Custom-strategy "pit" helpers (compute_*_pit) all use trailing windows
     that exclude the evaluation bar.
   - Realized-vol pricing uses up-to-today σ for TODAY's mark only (standard
     BS convention) — not for tomorrow's sizing.

4. CACHING DISCIPLINE
   - All external HTTP lives in data_providers.py wrapped with
     @st.cache_data(ttl=86400, show_spinner=False).
   - FINRA short-volume history in app.py uses ThreadPoolExecutor for
     parallel fetch (12-month window of daily files).

5. OPTIONS PRICING IS HONEST
   - _bs_call_price uses math.erf-based normal CDF — NO scipy import in the
     entire codebase. Boundary safe (returns intrinsic when T<=0 or σ<=0).
   - Trailing realized vol is clipped to [min_sigma, max_sigma] to avoid
     pathological pricing when the rolling window is too short.
   - Asymmetric resize is intentional: sell-down freely (locks in profits or
     shrinks exposure), refill ONLY at roll events. This is what makes
     "limited downside = premium" actually hold in simulation.

6. SECRETS / INTEGRATIONS
   - Anthropic Claude runs via Replit AI Integrations:
       AI_INTEGRATIONS_ANTHROPIC_BASE_URL
       AI_INTEGRATIONS_ANTHROPIC_API_KEY
     (auto-provisioned, no user API key needed; uses Replit credits).
   - Market data:
       EODHD_API_KEY       (equity history)
       POLYGON_API_KEY     (options snapshot + history)
   - SESSION_SECRET is reserved for future server-side session use (not yet
     consumed in code).

7. CUSTOM STRATEGY SCHEMA
   - The catalog constants in custom_strategy.py (ALL_INDICATORS, OPERATORS,
     APP_SIGNALS_*, DEFAULT_N / DEFAULT_N2) are the SINGLE SOURCE OF TRUTH.
   - strategy_nl.py mirrors them inside _indicator_catalog_text() — when adding
     a new indicator, update BOTH places or the LLM will emit invalid rules.
   - Saved strategies live in .local/saved_strategies.json (gitignored area).
   - Bump SIGNAL_VERSION when changing point-in-time signal computation so
     stale saved strategies can be detected and warned.

8. REPORT DOWNLOADS
   - Every backtest sub-tab that produces stats funnels into
     _render_download_buttons → backtest_engine.build_report_{text,csv,docx,pdf}.
   - The methodology string passed in MUST faithfully describe the actual
     implementation. Mismatches (e.g. claiming continuous refill when the
     engine is asymmetric) are treated as bugs.

9. WORKFLOW
   - Single Replit workflow named "Start application":
       streamlit run app.py --server.port 5000
   - Port 5000 is the only port exposed. Frontend + backend share it.
   - Use restart_workflow after editing app.py / backtest_ui.py / any file
     imported at startup. Streamlit auto-reloads source on save but the
     module cache for heavy imports is not always invalidated cleanly.
