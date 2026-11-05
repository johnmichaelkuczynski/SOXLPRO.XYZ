---
name: One-button diagnostic contract
description: User-requested comprehensive checks, honest coverage, and preservation of the working chart.
---

The user requires one button—“just one button”—to verify that the app's features are present and work. Do not turn this into a checklist of separate buttons or a confirmation workflow.

**Why:** The user explicitly requested a comprehensive, single-action diagnostic function after repeated chart and benchmark regressions.

**How to apply:** Run live service and browser checks together with controlled engine regressions. Clearly distinguish live requests from fixture tests and availability-only checks. Missing capabilities, skipped tests and unavailable test dependencies must never count as passes. Do not claim a health check establishes forecast accuracy or every possible interaction.

Diagnostic exercises must preserve the user's actual drawings, selection, viewport and chart instance.

**Why:** Testing show/hide, erase, reset or drawing controls in the user's chart would itself destroy the continuity the diagnostics are meant to protect. Same-origin cloned frames also share storage and messages unless explicitly isolated.

**How to apply:** Exercise mutable chart controls only in an isolated copy with no shared preference writes or sibling broadcasts. Inspect the original graph read-only and compare it after completion. Report failures with evidence rather than changing providers, billing, authentication or market state as part of a diagnostic run.
