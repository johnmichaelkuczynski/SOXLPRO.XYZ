---
name: Streamlit background-job ownership
description: Session isolation and completion semantics for cancellable research workers.
---

Background work must use a random identifier stored within each user's session, never the object identity of Streamlit's session-state proxy.

**Why:** That proxy can be shared across sessions; treating its identity as a user identity can incorrectly reuse another user's job or results.

**How to apply:** Keep job ownership, cancellation, and result capture scoped to the stored session identifier. Fragment polling updates only its fragment; completion must explicitly transfer the result to the surrounding page before announcing that the result is displayed.