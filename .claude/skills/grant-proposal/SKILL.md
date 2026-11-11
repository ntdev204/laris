---
name: grant-proposal
description: >-
  Writes research and project proposals mapped to a funder's criteria: significance, specific aims, approach, innovation, feasibility and preliminary results, timeline, budget justification, broader impact, risk and mitigation, and a reviewer-style self-critique. The funder's call text is an input and is verified by search. Delivers via the docx skill unless the funder supplies another template. Use whenever the user prepares a grant, fellowship, scholarship, project, or funding application, or a thesis/research proposal judged against criteria, e.g. "write a proposal for NAFOSTED", "draft specific aims", "budget justification", "check my proposal against the call", including the same requests written in Vietnamese.
model: claude-opus-5-5
effort: high
---

# Grant Proposal

Reply to the user in Vietnamese. Keep technical terms and math notation in standard English/LaTeX.
The proposal is written in the language the funder requires (record it before drafting).

## Purpose
Produce a proposal that answers exactly what the funder scores, makes a convincing case for significance and
feasibility, and survives a critical panel review.

## When to use / When NOT to use
Use for: grant, fellowship, project, and funding proposals; research proposals evaluated against criteria.
Do NOT use for:
- Scientific papers -> scientific-writing.
- Internal multi-year planning without a funder -> research-roadmap.

## Inputs to confirm before starting
Check project memory first: project-context.md (researcher, advisor, lab), research-state.md (gap, results),
decisions-log.md, verified-references.md.
Then confirm: funder and call (call text or URL), eligibility, deadline, page/word limits, template,
language, budget ceiling and rules, team members and roles, preliminary results available.

## Model & Effort
- Recommended model: Claude Opus 5.5 (`claude-opus-5-5`)
- Effort: high
- Rationale: A proposal must align significance, aims, feasibility, budget, and risk into one argument judged
  against explicit criteria; weak framing or a mismatch with the call loses the funding round. This
  high-stakes persuasive and strategic reasoning justifies the maximum configuration.
- Escalate: already at maximum.
- De-escalate to Sonnet 5.5 medium for formatting into the template, compliance checks against limits,
  and budget table arithmetic review after the content is fixed.
- Code: budget calculations or Gantt charts from data go to a Haiku 5.5 subagent via the Agent tool
  (`model: "haiku"`), or the `xlsx` skill for budget sheets; review results.

## Workflow
1. Obtain the call text; verify it on the funder's official page (cite URL and date). Extract the review
   criteria, required sections, limits, and eligibility into a compliance table.
2. Map content to criteria ([references/proposal-templates.md](references/proposal-templates.md)):
   significance, aims, approach, innovation, feasibility (preliminary results), timeline, budget
   justification, broader impact, risks and mitigation.
3. Draft specific aims first and confirm with the user; then the full draft.
4. Reviewer-style self-critique: score the draft against each criterion as a panel would; list weaknesses
   and fix them (or hand off to research-critique for an independent pass).
5. **Build with the built-in `docx` skill** (load its SKILL.md first), following the funder's template
   exactly if supplied; use another format only if the funder requires it.
6. Compliance check: limits, required sections, attachments, eligibility statements.

## Honesty and verification rules
- Funder rules and criteria only from the verified call text.
- Preliminary results only from real work; no inflated feasibility claims.
- Budget items realistic and justified; mark estimates as estimates.
- References verified.

## Output format
Proposal .docx (or the funder's format), compliance table, and self-critique summary.
Chat reply (Vietnamese) with what was produced, open compliance issues, and end-of-answer block.
Write back to project memory: funder, call, deadline -> project-context.md; aims and status ->
research-state.md; strategic choices -> decisions-log.md; open items -> open-questions.md.

## Handoffs
- Before: research-gap, research-design, research-roadmap.
- After: research-critique (independent review), research-integrity (ethics, data management plan).

## Quality checklist
- [ ] Reply in Vietnamese; memory checked first.
- [ ] Call text verified; compliance table complete.
- [ ] Every criterion explicitly addressed.
- [ ] Self-critique done and weaknesses addressed.
- [ ] Built with the docx skill or the funder's template.
- [ ] Limits and required attachments checked.
