---
name: Panel gesture priority
description: Resolve drag-anywhere panel behavior without stealing chart-slider gestures.
---

**Rule:** Treat chart-size slider gestures as control input, not panel movement.
Keep the panel movable from its other surfaces.

**Why:** The earlier literal interpretation of “drag anywhere” made slider drags
move the panel at the same time. The user's later difficulty using both sliders
requires this exception to that earlier interaction requirement.

**How to apply:** When changing panel drag handling, preserve slider gesture
priority and verify real thumb drags change chart dimensions while panel position
stays fixed. Programmatically setting a slider or focusing it does not verify this.

**Sizing rule:** Widening the panel must widen its controls to consume the new
space, including in the one-column layout; do not leave controls at a fixed
internal width or merely rearrange miniature controls into columns.

**Why:** The panel's resize affordance is only useful if the controls themselves
become easier to use rather than leaving an empty strip inside the wider panel.