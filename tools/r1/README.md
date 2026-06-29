# R1 — Synthetic User-Agent Harness for SOXL Analysis Platform

R1 is a Playwright-driven beta-tester that exercises the SOXL Analysis Platform end-to-end, captures raw evidence of every interaction (screenshots + numeric outputs + structured JSON), runs eight critical invariant checks (A–H), and emits a reviewable HTML report.

R1 is intentionally **not** a green-checkmark theater. PASS/FAIL exists only as a filter for `failures.md`. The deliverable is the raw evidence in `runs/<timestamp>/`.

---

## Install

From this directory:

```bash
npm install
```

`postinstall` runs `playwright install chromium` automatically. If you installed the deps from the workspace root (e.g. via the Replit packager), the postinstall hook does not run — install the browser binary manually:

```bash
npx playwright install chromium
```

The harness will fail to launch a browser if this step is skipped.

---

## Known limitations

- **Streamlit dataframe extraction (`st.dataframe`)** is rendered as a Glide canvas-based grid. R1 reads cells via accessibility attributes (`role="gridcell"`, `aria-rowindex`, `aria-colindex`) and scrolls to capture virtualized rows, but if Streamlit changes the underlying renderer or the cell text is image-only, extraction can return empty rows. **When this happens, the affected invariant is marked `unverified` (not pass)** and a HARNESS SANITY FAILURE is logged. This is intentional — no green-check theater.
- **Slider mutation** in Streamlit is awkward via Playwright. Function 11 (custom parameters) is best-effort and may not actually move sliders on all builds; the harness logs whether a real mutation was applied.
- **Trend-line drag** on the custom chart component is not attempted (fragile). R1 only verifies the iframe loads.
- **Custom Strategy save/load/delete (F18 advanced flow)** is not fully exercised — only the form-builder area is captured.

---

## Configuration

R1 reads environment variables. The defaults work out of the box on Replit:

| Var | Default | Purpose |
|---|---|---|
| `APP_URL` | `http://localhost:5000` | SOXL app URL |
| `HEADLESS` | `false` | `true` for headless; default lets the live view show R1's actions |
| `LIVE_VIEW_PORT` | `7777` | Port for the live-view HTTP server |
| `SKIP_FUNCTIONS` | (none) | Comma-separated function numbers to skip, e.g. `7,16,19` for AI-dependent fns |
| `ALLOCATION_ENGINE_TIMEOUT_MS` | `300000` | Function 9 timeout |
| `VOL_SURFACE_TIMEOUT_MS` | `180000` | Function 5 timeout |
| `AI_STRATEGY_TIMEOUT_MS` | `120000` | Functions 7, 16, 19 timeout |
| `ANTHROPIC_MODEL` | `claude-opus-4-7` | Model for R1 brain + judge. Override if your account doesn't have access. |
| `ANTHROPIC_API_KEY` | falls back to `AI_INTEGRATIONS_ANTHROPIC_API_KEY` | API key |
| `ANTHROPIC_BASE_URL` | falls back to `AI_INTEGRATIONS_ANTHROPIC_BASE_URL` | Base URL (Replit Integrations endpoint by default) |

**Note on credits:** by default R1's brain + judge run through the same Replit AI Integrations endpoint the SOXL app uses, so R1 consumes Replit credits. To bill against a personal Anthropic account, set both `ANTHROPIC_API_KEY` and unset `ANTHROPIC_BASE_URL` (or set it to `https://api.anthropic.com`).

---

## Run

Full plan:

```bash
npm start
```

Smoke run (skip AI-dependent functions when no Anthropic credentials):

```bash
npm run smoke
```

Startup banner:

```
R1 is running.
Live view:    http://localhost:7777
Output dir:   ./runs/<timestamp>/
Watch the live view — especially the SOXL Analysis State panel.
Do not trust summary output alone.
```

Finish banner lists exact paths to every artifact.

---

## Deliverables (per run)

```
runs/<ISO-timestamp>/
  transcript.jsonl          # one JSON line per interaction
  report.html               # self-contained, grouped by function, sticky TOC
  failures.md               # opens with CRITICAL INVARIANT VIOLATIONS
  run-summary.txt           # numeric counts (interactions / judge concerns / invariant violations)
  console.log               # full stdout
  network.log               # HTTP requests observed during the run
  screenshots/              # numbered PNGs (3 per interactive step, 1 for navigation)
  outputs/
    backtest/
      allocation-engine-default.json       # Function 9
      allocation-engine-custom.json        # Function 11
      look-ahead-test/                     # Function 10 cross-date determinism
      zero-day-test/                       # Function 10 degenerate input
    probability-engine/                    # Functions 4 + 13
    vol-surface/                           # Function 5
    dislocation/                           # Function 6
    strategy-builder/response.json         # Function 7 AI response + parsed JSON
    custom-strategy/
      form-spec.json                       # Function 18 form-built spec
      nl-spec.json                         # Function 19 NL-built spec
    downloads/                             # Function 21 exported reports
```

---

## The eight critical invariants

R1 verifies these. Any breach is logged in `failures.md` and triggers exit code 2.

| Invariant | Check |
|---|---|
| **A** | Allocation panel rows all in `[hard_floor=0.02, hard_ceiling=0.98]` AND `[user_floor, user_ceiling]` |
| **B** | Cross-date determinism: equity at date D from a run ending at D matches a run ending after D |
| **C** | Asymmetric sleeve resize: sells down freely, refills only at roll events |
| **D** | Every Probability Engine row reports `n` (sample size) |
| **E** | Risk Metrics dataframe renders all 9 columns even on zero-day inputs |
| **F** | Dislocation verdict bucketing is monotonic with Z-score |
| **G** | AI Strategy Builder JSON parses and matches documented schema |
| **H** | NL Custom Strategy JSON normalizes; indicators ∈ `ALL_INDICATORS`; operators ∈ `OPERATORS` |

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Clean — no judge concerns, no invariant violations, no harness sanity failures |
| `1` | Judge concerns raised |
| `2` | At least one CRITICAL invariant violation |
| `3` | Harness sanity failure (e.g. an interactive step captured 0 screenshots) |

---

## Live view

`http://localhost:7777`

Three panels:

- **Top** — current step, R1's parameter choices, URL, latest screenshot
- **Middle** — parsed numerics, judge critique, **SOXL Analysis State** panel:
  - active tab + sub-tab
  - date range
  - latest allocation-engine result (total return, sleeve %, regime)
  - latest dislocation (Z + verdict)
  - latest probability query (P + n)
  - invariant check status (A–H)
  - for allocation runs: first/last 10 per-bar allocation rows for floor/ceiling scan
- **Bottom** — reverse-chronological completed-interaction log

Page auto-refreshes every 2 seconds. After the run: a `RUN COMPLETE` banner stays up for 60 seconds with the report path.
