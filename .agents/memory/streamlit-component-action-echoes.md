---
name: Streamlit component action echoes
description: Apply chart state in component callbacks to avoid stale argument echoes and redundant reruns.
---

When a custom component action changes state used earlier in the script, prefer its `on_change` callback so state is applied before the script builds its arguments. Deduplicate action events. Only use a guarded second rerun when a callback cannot handle the action.

**Why:** Handling the action after rendering delivers old arguments during its first round trip. Adding another full rerun then rebuilds the page unnecessarily and can detach an iframe during interaction. Component values also remain available on later reruns; replaying an old action can overwrite a newer choice made through another control.

**How to apply:** Verify both disappearance and restoration of the real plotted trace through the running Streamlit host, not only that the iframe posts a message. Use the JSON data-type envelope for custom component values.

Purely visual benchmark hide/show controls must not send a Streamlit widget event at all. Keep the series loaded and change visibility inside the existing plot; synchronize display controls in the browser.

**Why:** Even a correctly handled callback still reruns the server script. The user explicitly reported seconds of blanking and loss of continuity when hiding benchmarks, so eventual reappearance is not sufficient verification.

**How to apply:** Verify that both the button row and panel checkboxes retain the same iframe and plotted SVG, preserve axis ranges, and leave SOXL visible on every sampled animation frame. Benchmark display preferences belong to the browser session, not to server-side data loading.

Component updates must also reach already-open previews, not just new browser sessions.

**Why:** An existing iframe can retain previously loaded JavaScript even after server-side files change. A passing fresh-browser test does not establish that an open tab received the fix.

**How to apply:** Give changed component bundles content-versioned identities and exercise an open tab across the update without manually reloading it. Normal display toggles must still reuse that updated iframe.
