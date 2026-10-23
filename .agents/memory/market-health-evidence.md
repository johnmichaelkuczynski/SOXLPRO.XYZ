---
name: Market health evidence
description: Why optional health evidence must not gate saved results or imply a chart refresh.
---

Treat health telemetry as optional to market-data availability, and distinguish the displayed analysis snapshot from the latest background update.

**Why:** A worker may be disabled or its health storage unavailable while saved market results remain usable. Open chart sessions intentionally retain their analysis and drawings; a diagnostics refresh must not imply the chart adopted newer data.

**How to apply:** Keep telemetry failures independent of primary reads and updates. Recheck database evidence even on cached fallback pages, and label newer background results separately from the displayed analysis.
