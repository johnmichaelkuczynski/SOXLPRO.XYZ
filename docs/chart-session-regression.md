# Open chart session regression

Run `npm run test:chart-session` from the repository root. Requires the project's
Python dependencies, Playwright, Chromium (`CHROMIUM_PATH` overrides the default
`/repl/tools/bin/chromium`), and readable saved development market data. Like an
anonymous visit to the app, this may update development visitor/analytics data.
It does not create market fixtures, refresh providers, or use production data.

The runner starts the real Streamlit app and the real gateway handlers on
isolated ports 5100/5101 (`SESSION_TEST_PORT` changes the pair). It does not
restart the preview or start market-refresh workers. Server processes are
terminated even on assertion failure.

One browser page is opened once. A drawing is submitted through Plotly's
relayout event and the component's normal Streamlit value handoff, then the
chart is zoomed. The test:

1. Decodes real Streamlit WebSocket messages to identify the chart fragment
   and wait for its successful timed execution, then requires
   drawing, axis ranges, and iframe identity to survive.
2. Closes the actual Streamlit WebSocket, refuses reconnects for three seconds,
   then requires reconnection, another successful fragment run, and retained state.
3. Terminates only its own backend process, launches a new backend, and
   requires recovery plus another real fragment update in the same page.
   Drawing and viewport retention are asserted; iframe retention is also reported.

The backend-restart check protects the observed open-tab retention behavior.
It does not promise durable drawing storage across a page reload: the current
app stores drawings in process-local Streamlit sessions. The JSON report
records actual before/after values, including state loss on failure.
Recovery means a rendered chart with no Streamlit exception or fatal recovery
panel, not merely a successful health endpoint or an available Reopen button.
The runner asserts that there was no top-level navigation after initial load.

Unchanged cached market data may not re-execute an iframe script. Therefore
counting postMessage deliveries is not a reliable fragment execution check.
The decoder identifies the fragment by its actual market-update content and
counts only its successful fragment-run completions.

Allow roughly four minutes. Logs, screenshots, and the machine-readable
`report.json` are written under `generated-artifacts/chart-session/` (excluded
from Git and deployment). A failed assertion returns a nonzero exit code.
This is a real application integration test, so unavailable saved data or a
blocked Plotly CDN causes an explicit failure rather than substituted data.
It covers desktop Chromium; it does not establish mobile, other browser, or
long-offline-session behavior.
