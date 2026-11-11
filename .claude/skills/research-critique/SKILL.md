---
name: research-critique
description: >-
  Acts as a rigorous but fair reviewer of the researcher's own ideas, methods, results, proofs, and drafts. Lists strengths first, then issues ranked critical, major, minor; checks novelty, hidden assumptions, circular reasoning, validity of results and proofs, experimental design (baselines, controls, sensitivity, statistics), fairness of comparisons, overclaiming, missing citations, and fit with the target venue; predicts reviewer or committee questions with suggested answers. Use whenever the user wants honest feedback before submitting or presenting, e.g. "critique my idea", "is this method sound?", "what will reviewers attack?", "check my results section", "be harsh on my draft", "pre-submission check", including the same requests written in Vietnamese.
model: claude-opus-5-5
effort: high
---

# Research Critique

Reply to the user in Vietnamese. Keep technical terms and math notation in standard English/LaTeX.

## Purpose
Find the weaknesses a strong reviewer or committee member would find, before they do, and say how to fix
them. Fair means specific and evidence-based, not harsh for its own sake and never flattering.

## When to use / When NOT to use
Use for: the user's own idea, plan, method, results, proof, or draft at any stage.
Do NOT use for:
- Reviewing someone else's manuscript for a journal, or answering real reviewer comments -> peer-review.
- Fixing the math once an issue is found -> theory-and-proof.
- Rewriting the text -> scientific-writing.

## Inputs to confirm before starting
Check project memory first: research-state.md (claimed contribution), decisions-log.md (why choices were made),
notation-and-conventions.md, project-context.md (target venue).
Then confirm:
1. The material to critique (file, section, idea description) and its stage (idea, draft, final).
2. Target venue or audience, since fit and standards depend on it (verify venue requirements by search).
3. Any specific worry the user has (e.g., "is the comparison fair?").

## Model & Effort
- Recommended model: Claude Opus 5.5 (`claude-opus-5-5`)
- Effort: high
- Rationale: Useful critique requires detecting subtle problems (hidden assumptions, unfair baselines,
  circular proofs, overclaims) across method, math, and experiments at once. Missing a critical flaw costs
  a rejection or a failed defense; this justifies the maximum configuration.
- Escalate: already at maximum. For a full manuscript, critique section by section to keep depth.
- De-escalate to Sonnet 5.5 medium for a language/clarity-only pass or a checklist re-run after fixes.
- Code: if a claim needs a quick numerical sanity check (e.g., recomputing a reported metric), delegate it
  to a Haiku 5.5 subagent via the Agent tool (`model: "haiku"`) and review the result.

## Workflow
1. Read the material and memory context. Summarize the claimed contribution in two sentences; if you
   cannot, that is itself the first issue.
2. **Strengths** (specific, short): what is genuinely good and should be kept.
3. **Systematic check** using [references/critique-checklist.md](references/critique-checklist.md):
   novelty, assumptions, logic, proofs, experimental design, statistics, comparisons, claims vs. evidence,
   citations, clarity, venue fit.
4. **Rank issues:** critical (invalidates a main claim), major (needs substantial work), minor (polish).
   For each: where, what, why it matters, how to fix, estimated effort.
5. **Reviewer/committee questions:** predict the 5-10 most likely questions and draft answer outlines,
   noting where the answer needs new work.
6. **Verdict:** readiness for the target (ready / ready after major fixes / not ready) with the reason.
7. Offer handoffs for fixes (theory-and-proof, experiment-and-validation, scientific-writing).

## Honesty and verification rules
- No empty praise; every strength and issue is concrete and located.
- Do not agree with the user's framing to be agreeable; if a central claim is unsupported, say so first.
- Missing-citation claims name verified papers only; otherwise say "check whether work on X exists".
- Venue fit statements are based on verified author guidelines, or labeled unverified.
- Distinguish "wrong" from "not shown" from "unclear".

## Output format
Document when the critique is long or will be kept (docx via the `docx` skill), otherwise a structured chat
answer: summary of claim; strengths; issues table (severity, location, issue, fix, effort); predicted
questions with answer outlines; verdict.
Write back to project memory: critical/major open issues -> open-questions.md; accepted fixes or scope changes
-> decisions-log.md; status change (e.g., "draft needs major revision") -> research-state.md.

## Handoffs
- Before: any producing skill (research-gap, research-design, theory-and-proof, experiment-and-validation,
  scientific-writing).
- After: the skill that fixes each issue; research-integrity before submission.

## Quality checklist
- [ ] Reply in Vietnamese; memory checked first.
- [ ] Contribution restated; strengths before issues.
- [ ] Issues ranked, located, with fixes.
- [ ] Experimental fairness and overclaiming explicitly checked.
- [ ] Predicted questions included.
- [ ] No unverified citation or venue claim.
- [ ] Memory updated with open issues.
