---
name: Loopback WebSocket origins
description: Safe Origin handling when a public Node proxy forwards Streamlit WebSockets to loopback.
---

Validate a browser WebSocket Origin against the incoming public Host at the front proxy. After validation, omit that Origin when forwarding the upgrade to a loopback Streamlit server.

**Why:** Streamlit compares the public browser Origin with the private loopback host and rejects the handshake. Blindly stripping Origin fixes connectivity but removes the public boundary's cross-origin protection.

**How to apply:** For browser upgrade requests, accept only same-host HTTP(S) origins, reject mismatches explicitly, and strip the already-validated Origin only for the private proxy hop.