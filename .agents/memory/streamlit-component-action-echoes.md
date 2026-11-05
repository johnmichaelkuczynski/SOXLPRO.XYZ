---
name: Streamlit component action echoes
description: Apply chart state in component callbacks to avoid stale argument echoes and redundant reruns.
---

When a custom component action changes state used earlier in the script, prefer its `on_change` callback so state is applied before the script builds its arguments. Deduplicate action events. Only use a guarded second rerun when a callback cannot handle the action.

**Why:** Handling the action after rendering delivers old arguments during its first round trip. Adding another full rerun then rebuilds the page unnecessarily and can detach an iframe during interaction. Component values also remain available on later reruns; replaying an old action can overwrite a newer choice made through another control.

**How to apply:** Verify both disappearance and restoration of the real plotted trace through the running Streamlit host, not only that the iframe posts a message. Use the JSON data-type envelope for custom component values.
