# Design templates

## Research question patterns
- "Under [conditions], does [method] achieve [property/metric] compared with [baseline]?"
- "What conditions on [parameters] guarantee [property] for [system]?"
- "How sensitive is [outcome] to [uncertainty source]?"

## Hypothesis pattern
H1: [Method] reduces [metric] by at least [margin] relative to [baseline] in [scenario set].
Refuted if: [observation], measured by [procedure].

## Methodology table
| RQ | Method | Why it fits | Alternative rejected | Why rejected | Evidence produced |

## Validity threats
- Internal: confounds (tuning effort differs between methods; scenario selection).
- External: simulation-to-real gap; limited speeds/road conditions.
- Construct: metric does not capture the property claimed (e.g., RMS error vs. safety).
- Conclusion: too few runs; no variance reported.

## Pre-mortem prompt
"It is [date + 12 months] and the study failed. Why?" List causes, warning signs, and preventive actions.

## Risk register
| Risk | Likelihood (L/M/H) | Impact (L/M/H) | Mitigation | Trigger / warning sign | Owner |

## Milestones
| Milestone | Deliverable | Success criterion | Target date | Depends on |
