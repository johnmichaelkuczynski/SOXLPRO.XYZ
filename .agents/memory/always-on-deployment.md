---
name: Always-on deployment
description: User's Reserved VM preference and validated configuration-edit requirement.
---

Keep this app on the smallest suitable Reserved VM, not Autoscale.

**Why:** The user explicitly requested always-on hosting to avoid idle cold starts,
with the existing run command and port mappings preserved.

**How to apply:** Machine size is selected in Publishing settings; do not claim
it was selected merely because the target changed. Configuration changes take
effect only after the user republishes.

The deployment helper accepts `vm` but can write that literal value rather than
the user's requested `.replit` value `gce`. Direct `.replit` patches are blocked.

**Why:** The helper's successful result did not satisfy the requested file value.

**How to apply:** When the exact value matters, inspect the resulting TOML.
Use the platform's validated temporary-file replacement flow for `.replit`,
and compare the parsed configuration to ensure unrelated settings stay intact.
