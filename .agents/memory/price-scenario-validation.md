---
name: Price scenario validation boundaries
description: Counterfactual and retrospective limits of entry-price validation.
---

Keep slider estimates exploratory after retrospective evaluation; observed historical entry closes cannot establish outcomes for arbitrary counterfactual prices on the same date.

**Why:** There is no observed outcome for an alternative same-date entry price. The project's historical snapshot has already been used in other research, so a method-frozen holdout is not globally unseen or a prospective trial.

**How to apply:** Describe historical evaluation as pseudo-out-of-sample, freeze the method before scoring, and identify any changed method or data as a separate experiment. Do not retune on the existing evaluation or change the frozen daily NO EDGE rule.
