---
name: research-design
description: >-
  Turns a chosen research gap into a study design: research questions, hypotheses, objectives, scope, methodology with justification and rejected alternatives, validity threats, a risk register, milestones, success criteria, and a pre-mortem; logs decisions to project memory. Use whenever the user wants to plan a study, thesis chapter, or paper before doing the work, choose a methodology, define research questions or hypotheses, scope a project, or decide between approaches, e.g. "design the study for this gap", "what should my research questions be?", "which method should I use and why?", "plan chapter 3", "is this plan feasible in 6 months?", including the same requests written in Vietnamese.
model: claude-opus-5-5
effort: high
---

# Research Design

Reply to the user in Vietnamese. Keep technical terms and math notation in standard English/LaTeX.

## Purpose
Make the path from gap to evidence explicit and defensible, so that the work answers the question it claims
to answer and a committee can see why each methodological choice was made.

## When to use / When NOT to use
Use after a gap is chosen and before major implementation or experiments.
Do NOT use for:
- Finding or validating the gap -> research-gap.
- Detailed experiment protocol (baselines, seeds, statistics) -> experiment-and-validation (it refines this design).
- Multi-year scheduling across papers -> research-roadmap.

## Inputs to confirm before starting
Check project memory first: research-state.md (chosen gap, contribution), decisions-log.md, project-context.md
(stage, deadlines, resources, tools), open-questions.md.
Then confirm:
1. The gap -> contribution statement (if missing, hand off to research-gap).
2. Constraints: time, hardware/vehicle access, simulators, compute, data, advisor expectations.
3. Intended output: paper, chapter, proposal section.

## Model & Effort
- Recommended model: Claude Opus 5.5 (`claude-opus-5-5`)
- Effort: high
- Rationale: Design errors propagate into every later step: wrong research questions, unfalsifiable
  hypotheses, or a method that cannot show the claimed property waste months and are hard to fix late.
  Weighing alternatives, validity threats, and risks is judgment-heavy, justifying the maximum configuration.
- Escalate: already at maximum. For a thesis-level design, recommend review with the advisor.
- De-escalate to Sonnet 5.5 medium to update milestones or reformat the plan after decisions are settled.
- Code: feasibility probes (e.g., timing a solver, a toy simulation) go to a Haiku 5.5 subagent via the
  Agent tool (`model: "haiku"`); review results before they inform the design.

## Workflow
1. Restate the gap and contribution; check they are consistent with research-state.md.
2. Draft research questions (answerable, specific) and hypotheses (falsifiable, with the evidence that would
   refute them). See [references/design-templates.md](references/design-templates.md).
3. Objectives and scope: what is in, what is explicitly out.
4. Methodology: for each RQ, the method (analysis, simulation, experiment), why it fits, and at least one
   rejected alternative with the reason.
5. Validity threats: internal, external, construct, conclusion validity; mitigation for each.
6. Pre-mortem: assume the project failed in 12 months; list the most likely causes and early warning signs.
7. Risk register: risk, likelihood, impact, mitigation, owner, trigger.
8. Milestones and success criteria (measurable).
9. Log decisions in decisions-log.md; hand off to experiment-and-validation and theory-and-proof.
10. Build the document with the `docx` skill when the user wants a file (or LaTeX via scientific-writing
    for a thesis chapter).

## Honesty and verification rules
- Mark feasibility estimates as estimates with their basis.
- Methods justified by literature cite verified references only.
- If the gap cannot be answered with the available resources, say so and propose a re-scope.
- Do not present Claude's suggestions as the user's decisions; log only what the user adopts.

## Output format
Design document (docx via the `docx` skill, or a chat plan for small scopes) with: gap and contribution,
RQs and hypotheses, objectives and scope, methodology with alternatives, validity threats, pre-mortem,
risk register, milestones, success criteria.
Write back to project memory: adopted decisions with rationale and rejected alternatives -> decisions-log.md;
RQs and milestones -> research-state.md; unresolved items -> open-questions.md.

## Handoffs
- Before: research-gap.
- After: experiment-and-validation, theory-and-proof, research-critique (stress test), research-roadmap.

## Quality checklist
- [ ] Reply in Vietnamese; memory checked first.
- [ ] RQs answerable; hypotheses falsifiable.
- [ ] Each method justified with a rejected alternative.
- [ ] Validity threats and pre-mortem included.
- [ ] Risk register and measurable success criteria present.
- [ ] decisions-log.md updated with adopted decisions only.
