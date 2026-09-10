---
name: Streamlit analytics semantics
description: Count actual interactions rather than eager tab renders, and preserve events across reruns.
---

Count feature views from browser tab interactions, not from execution of Python tab bodies. Record successful outcomes only at their verified success branch.

**Why:** Streamlit eagerly renders every tab, including hidden tabs. Python execution alone would count unseen features. Immediate reruns can also replace an iframe before its event script executes.

**How to apply:** Keep browser click tracking separate from queued server-confirmed outcomes. Drain queued events after reruns and within dialog completion paths. Deduplication must include the event name so preparing and confirming the same checkout remain distinct events. These analytics are best-effort engagement signals, not an authoritative financial ledger.