# Critique checklist

## Novelty and contribution
- Is the contribution stated explicitly and specifically? Is it new relative to verified prior work?
- Is it an increment that matters, or a recombination without insight?

## Assumptions and logic
- Hidden assumptions (known parameters, no delay, perfect state estimate, constant speed, no slip)?
- Are assumptions realistic for the claimed application? Are they stated where they are used?
- Circular reasoning (assuming what is proven; tuning on the test scenario)?

## Proofs and theory
- Statement precise? Conditions of cited theorems satisfied? Conclusion matches the claim?
- Continuous-time guarantees claimed for a discrete-time implementation without argument?

## Experimental design
- Baselines: strong, recent, correctly tuned, same information available?
- Controls and ablations: does each component's effect get isolated?
- Sensitivity: parameter variation, noise, model mismatch, initial conditions.
- Statistics: repetitions, seeds, variance or confidence intervals, appropriate tests.
- Scenarios: representative, include failure cases, not cherry-picked.
- Reproducibility: parameters, code, data availability.

## Claims vs. evidence
- Every claim in abstract and conclusion supported by a result? Words like "robust", "optimal",
  "real-time", "guarantees" justified?
- Simulation results presented as real-world performance?

## Citations
- Key related work missing? Self-citation balance? Citations used for what they actually show?

## Clarity
- Notation consistent? Figures readable and referenced? Can a reader reproduce the method?

## Venue fit
- Scope, length, format, and contribution type match the verified author guidelines?

## Typical reviewer questions (adapt)
- Why this baseline and not [stronger method]? How were baselines tuned?
- What happens under model mismatch / actuator saturation / delay?
- Is the method real-time on target hardware? Measured how?
- How does the guarantee survive discretization and constraints?
- What is new compared with [closest verified work]?
