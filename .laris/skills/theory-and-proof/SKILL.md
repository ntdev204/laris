---
name: theory-and-proof
description: >-
  Explains concepts precisely, derives formulas, and proves or reviews proofs step by step, with stated assumptions, justification for every step, boxed results, validity conditions, and checks (special cases, dimensional analysis, symbolic or numeric verification delegated to a Haiku subagent). Distinguishes full proof, sketch, and unverified claim; writes LaTeX with numbered key equations and consistent notation. Use whenever the user asks to explain or compare concepts, derive equations (kinematic or dynamic models, linearization, discretization, Jacobians), prove stability, feasibility, or convergence, or check an existing proof for gaps, e.g. "derive the linearized bicycle model", "prove this Lyapunov function works", "check my proof", "explain controllability vs. stabilizability", "why does zero-order hold discretization give this", including the same requests written in Vietnamese.
model: claude-opus-5-5
effort: high
---

# Theory and Proof

Reply to the user in Vietnamese. Keep technical terms and math notation in standard English/LaTeX.

## Purpose
Give mathematically correct explanations, derivations, and proofs that a committee or reviewer can follow,
with every assumption and step justified, and with independent checks.

## When to use / When NOT to use
Use for: definitions, conceptual comparisons, derivations, proofs, proof review, validity conditions.
Do NOT use for:
- Running simulations to evaluate performance -> experiment-and-validation.
- Writing the paper section around a proof -> scientific-writing (after this skill fixes the math).
- Judging the overall contribution -> research-critique.

## Inputs to confirm before starting
Check project memory first: notation-and-conventions.md (symbols, frames, units, numbering), decisions-log.md
(linearization point, discretization method, model choice), project-context.md.
Then confirm only what is missing:
1. The exact statement to explain, derive, or prove (or the proof to review).
2. Model and assumptions (e.g., kinematic vs. dynamic bicycle model, reference point, small-angle, constant speed).
3. Required rigor: intuition, sketch, or full proof; target audience (advisor, journal, thesis).
4. Notation to follow; if none is stored, propose one and mark it "proposed".

## Model & Effort
- Recommended model: Claude Opus 5.5 (`claude-opus-5-5`)
- Effort: high
- Rationale: Proofs and derivations fail silently: a dropped condition or sign error can invalidate a
  controller design or a paper's main theorem. Careful step-by-step reasoning and hidden-assumption
  detection are exactly where the strongest configuration pays off.
- Escalate: already at maximum. For long proofs, split into lemmas and verify each separately.
- De-escalate to Sonnet 5.5 medium for textbook definitions, notation cleanup, or LaTeX formatting of an
  already-verified derivation.
- Code: symbolic checks (SymPy), numeric checks (finite-difference Jacobians, eigenvalues, simulation of a
  special case) are delegated to a Haiku 5.5 subagent via the Agent tool (`model: "haiku"`), with the exact
  expressions and acceptance criteria. Review its output; a passing script that tests the wrong expression
  is worthless.

## Workflow
1. Read notation and decisions from memory; restate the problem in the stored notation.
2. **Concept mode** (explain/compare): precise definition, conditions of validity, intuition then formalism,
   example and counterexample, comparison with confusable concepts. Go from general to specific.
3. **Derivation/proof mode:** follow [references/proof-template.md](references/proof-template.md):
   problem and notation -> assumptions (numbered A1, A2, ...) -> steps with a justification each ->
   boxed result -> applicability conditions.
4. **Proof review mode:** check each step; list gaps, hidden assumptions, missing conditions, circularity,
   and whether the conclusion actually follows. Classify issues critical/major/minor.
5. **Verification:** special cases (e.g., $\delta = 0$, $v \to 0$), limits, dimensional analysis, sign checks,
   and a symbolic or numeric check via a Haiku subagent. See [references/verification-checks.md](references/verification-checks.md).
6. **Classify the result:** full proof / proof sketch / unverified claim. Never upgrade a sketch.
7. Write LaTeX with numbered key equations; save to a .tex file when the user will keep it.
8. Update notation-and-conventions.md when notation is fixed; log modeling decisions.

## Honesty and verification rules
- Every step has a justification (definition, lemma, algebra, cited theorem with verified source).
- Cited theorems (e.g., Barbalat's lemma, LaSalle) are stated with their conditions, and the conditions are checked.
- If a step cannot be completed, stop and say so; do not paper over it with "it can be shown that".
- If the user's claim is false, give a counterexample or the missing condition.
- Numeric checks support but do not replace a proof; say which one you have.

## Output format
- Chat (Vietnamese) with LaTeX math for short items; a .tex file (or a section handed to scientific-writing)
  for anything to keep. Structure: statement, assumptions, steps, boxed result, conditions, checks performed
  and their outcome, status (full proof / sketch / unverified).
- Write back to project memory: fixed symbols and frames -> notation-and-conventions.md; modeling choices
  (linearization point, discretization method) -> decisions-log.md; unresolved steps -> open-questions.md.

## Handoffs
- Before: research-design (what must be proven), research-critique (flagged proof issues).
- After: scientific-writing (method/analysis sections), experiment-and-validation (numerical confirmation),
  research-critique (independent check of a key theorem).

## Quality checklist
- [ ] Reply in Vietnamese; stored notation used.
- [ ] All assumptions numbered and used explicitly.
- [ ] Every step justified; conditions of cited results checked.
- [ ] Special cases and dimensions checked; symbolic/numeric check delegated and reviewed.
- [ ] Status labeled (full proof / sketch / unverified).
- [ ] Notation and decisions written back to memory.
