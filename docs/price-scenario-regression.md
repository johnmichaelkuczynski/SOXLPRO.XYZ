# Open-chart price scenario regression

Run `npm run test:price-scenario` from the repository root.

This uses Playwright and the real Streamlit app with its saved market snapshot.
The same dependencies as `npm run test:chart-session` are required: installed
Python application dependencies, Playwright, and Chromium at
`/repl/tools/bin/chromium` (override with `CHROMIUM_PATH`).

The runner starts an isolated backend on port 5120, refuses an occupied port,
and shuts down only its own child processes. Override the port with
`PRICE_SCENARIO_TEST_PORT`. It does not restart the preview, start market refresh
workers, modify saved market data, or reload the browser document between cases.
A missing saved snapshot is a failure, not a skipped or mocked success.

## Assertions

- A real mouse gesture draws a trendline. The date-range controls create an
  actual period analysis before scenario interactions begin.
- A non-default zoom, line data, iframe identity, period analysis summary, and
  existing daily and long-term signals remain unchanged after every scenario interaction.
- One, six, and twelve months complete real scenario fragment executions and
  display 21, 126, and 252 trading sessions.
- Physical thumb drag changes the price; ArrowRight changes it by one cent.
  The runner enters the custom slider iframe, reads the native range value,
  and calculates the thumb position from its current value and 20px thumb width.
- Dragging to the upper endpoint selects $500, shows the unsupported historical-range warning, and removes
  probability and median-price metrics.
- Use latest price restores the initial saved-quote selection.
- In the same session at a 390×844 viewport, controls fit the available width,
  dragging and reset still work, and the timeframe can still be changed.
- No main-document navigation, Streamlit exception, or browser page error occurs.

The WebSocket decoder observes successful completion of the specific scenario
fragment; changing a slider's DOM value alone cannot satisfy the test.

## Evidence and limitations

Logs, screenshots, and the per-interaction JSON report are written to
`generated-artifacts/price-scenario/` (ignored by Git and deployment).
On failure the runner exits nonzero and captures a screenshot and stack trace.

The saved snapshot must include the 2023–2024 analysis period and must have an
observed historical maximum below $500. The explicit upper-price assertion fails
if that market-data assumption stops being true; update the test data/unsupported
case rather than silently accepting numeric forecasts.

The narrow viewport check uses desktop Chromium mouse input, not a physical
touchscreen or mobile WebKit. It verifies responsive layout and pointer gestures,
not device-specific touch behavior. This regression protects UI isolation, not
the historical model's predictive validity.
