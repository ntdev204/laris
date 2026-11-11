---
name: research-gap
description: >-
  Identifies, classifies, falsifies, and ranks research gaps from a literature review, then turns the chosen gap into a gap-to-contribution statement ready for an Introduction. Classifies gaps (theoretical, methodological, experimental, application), builds a comparison matrix, runs targeted searches to check each gap, actively tries to find work that already fills it, and ranks by value, feasibility, risk, and fit. Use whenever the user asks whether an idea is novel, what is missing in the literature, where they can contribute, how to position a paper, or to validate a gap, e.g. "is this gap real?", "has anyone done adaptive MPC with tire slip on Ackermann?", "find a research gap", "what is my contribution", "novelty check", including the same requests written in Vietnamese.
model: claude-opus-5-5
effort: high
---

# Research Gap

Reply to the user in Vietnamese. Keep technical terms and math notation in standard English/LaTeX.

## Purpose
Find a gap that is real, valuable, and feasible for this researcher, and state it as a contribution that
survives reviewer scrutiny. The core discipline is falsification: try hard to prove the gap is already filled.

## When to use / When NOT to use
Use after (or with) a literature review, or when the user proposes an idea and asks if it is new.
Do NOT use for:
- Building the literature base from scratch -> literature-review first.
- Planning the study after the gap is chosen -> research-design.
- General critique of a draft -> research-critique.

## Inputs to confirm before starting
Check project memory first: research-state.md (current RQs, any earlier gap), verified-references.md,
decisions-log.md (rejected directions), project-context.md (thesis stage, venues, skills/resources).
Then confirm:
1. The literature-review output (extraction table) or the set of papers to compare against.
2. The researcher's constraints: time to deadline, hardware access, theoretical vs. experimental strength.
3. Target venue type (theory-heavy journal vs. application letter), which changes what counts as a contribution.

## Model & Effort
- Recommended model: Claude Opus 5.5 (`claude-opus-5-5`)
- Effort: high
- Rationale: Choosing a gap commits months of work and determines whether reviewers accept the novelty
  claim. Errors here (a gap that is already filled, or one that is trivial) are expensive and hard to spot.
  This judgment-heavy synthesis across many papers justifies the maximum configuration.
- Escalate: already at the maximum used in this workspace. For very high stakes (thesis direction),
  recommend the user also discusses the ranked list with the advisor.
- De-escalate to Sonnet 5.5 high for re-ranking after small input changes, or for reformatting the
  comparison matrix; to Sonnet medium for wording the final statement once the gap is fixed.
- Code (e.g., counting papers per method/assumption from a large table) goes to a Haiku 5.5 subagent
  via the Agent tool (`model: "haiku"`); verify its counts.

## Workflow
1. Load the extraction table (from literature-review) and memory context.
2. **Comparison matrix:** rows = papers, columns = dimensions that matter (model fidelity, assumptions,
   method, guarantees, validation type, scenario). See [references/gap-templates.md](references/gap-templates.md).
3. **Candidate gaps:** read empty or weak cells; classify each gap as theoretical, methodological,
   experimental, or application. Discard "gaps" that are empty because nobody needs them.
4. **Targeted verification:** for each candidate, run new specific searches (WebSearch; synonyms, adjacent
   fields such as mobile robotics, aerospace, process control). Record queries.
5. **Gap falsification:** actively look for work that already fills the gap: recent preprints, theses,
   other communities, different terminology. Report what you found and the remaining confidence
   (high / medium / low). "Not found" is evidence of absence only within the searched sources.
6. **Rank** surviving gaps on value, feasibility, risk, and fit to the researcher (scored table with reasons).
7. **Contribution statement:** for the chosen gap, write gap -> contribution -> how it will be shown,
   in 3-5 sentences usable in an Introduction, with an honest scope boundary.
8. **Record** the chosen gap in research-state.md; log the decision and rejected alternatives in decisions-log.md.
9. Offer handoff to research-design (to plan the study) and research-critique (to stress-test the claim).

## Honesty and verification rules
- Never claim "no prior work exists". Say "not found in [sources, date]; confidence: X".
- Every paper cited as filling or not filling a gap must be verified.
- Distinguish a real gap from a combination of known components with no new insight; say so if it is the latter.
- If the user's preferred gap is weak, say why and show a stronger alternative.

## Output format
Document (docx via the `docx` skill when the user wants a file; otherwise a structured chat answer) with:
comparison matrix; candidate gaps with type; verification and falsification log; ranking table;
chosen gap -> contribution statement; residual risks.
Write back to project memory: chosen gap and statement -> research-state.md; decision and rejected gaps
-> decisions-log.md; new verified references -> verified-references.md; unresolved checks -> open-questions.md.

## Handoffs
- Before: literature-review.
- After: research-design, research-critique, scientific-writing (Introduction).

## Quality checklist
- [ ] Reply in Vietnamese; memory checked first.
- [ ] Each gap typed and tied to specific verified papers.
- [ ] Falsification searches run and logged, with confidence stated.
- [ ] Ranking reasons explicit; weak preferred gaps challenged.
- [ ] Contribution statement is specific, scoped, and not overclaimed.
- [ ] research-state.md and decisions-log.md updated.
