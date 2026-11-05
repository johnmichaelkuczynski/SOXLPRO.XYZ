---
name: Streamlit component action echoes
description: Why chart selection actions need a guarded second render and event deduplication.
---

When a custom component action changes state used to build the component's arguments earlier in the script, apply the change and request a guarded full rerun. Deduplicate action events before doing so.

**Why:** The first rerun can deliver the new action while still rendering arguments from the previous state. Component values also remain available on later reruns; replaying an old action can overwrite a newer choice made through another control. A checkbox can appear unchecked while its plotted line remains visible unless the complete round trip is verified.

**How to apply:** Verify both disappearance and restoration of the real plotted trace through the running Streamlit host, not only that the iframe posts a message. Use the JSON data-type envelope for custom component values.
