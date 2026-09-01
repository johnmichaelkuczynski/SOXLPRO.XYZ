---
name: Streamlit cold-response metadata
description: Why runtime patches to Streamlit's static HTML can be absent from the first cold response
---

Patching Streamlit's installed `static/index.html` from the app script does not guarantee metadata on the first HTML response after process startup. Streamlit can serve its shell before executing the app script; the app runs when a frontend session connects.

**Why:** A cold root request returned the unpatched Streamlit shell. After a browser opened the app and established a session, the same root response contained the runtime-injected metadata.

**How to apply:** For metadata that must exist on the very first crawler request, arrange the patch before the Streamlit server starts or serve a separate static landing response. Runtime app-script injection is useful only as a secondary path for rendered sessions and later responses.