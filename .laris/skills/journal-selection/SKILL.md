---
name: journal-selection
description: >-
  Helps choose a journal or conference and prepares submission: scope fit verified on official pages, indexing and impact claims verified from official or indexing sources (never from memory), review time, open-access options and fees, predatory-venue red flags, a submission checklist, and a cover-letter handoff. Records the chosen venue in project memory. Use whenever the user asks where to submit, compares venues, checks whether a journal is legitimate, indexed, Q1, or open access, or asks about fees and review times, e.g. "should I submit to RA-L or T-ITS?", "is this journal predatory?", "which Q1 journals fit my paper?", "what does IEEE T-FS require?", including the same requests written in Vietnamese.
model: claude-sonnet-5-5
effort: medium
---

# Journal Selection

Reply to the user in Vietnamese. Keep technical terms and math notation in standard English/LaTeX.

## Purpose
Pick a venue that fits the paper and the researcher's goals, based only on verified, current information,
and prepare a clean submission.

## When to use / When NOT to use
Use for: venue shortlists, comparisons, legitimacy checks, submission requirements, checklists.
Do NOT use for:
- Formatting the manuscript to the template -> scientific-writing.
- Pre-submission ethics and disclosure checks -> research-integrity.

## Inputs to confirm before starting
Check project memory first: project-context.md (candidate and confirmed venues, deadlines),
research-state.md (paper type and status), decisions-log.md.
Then confirm: paper abstract or contribution, paper type and length, priorities (speed, prestige/quartile,
open access, cost, audience), deadlines, funding constraints on fees, any required indexing (e.g., for
graduation or institutional rules, which the user must state).

## Model & Effort
- Recommended model: Claude Sonnet 5.5 (`claude-sonnet-5-5`)
- Effort: medium
- Rationale: The work is mostly careful lookup and verification of official pages plus a structured
  comparison; Sonnet at medium handles this well. The main risk is stale or invented metrics, which is
  controlled by the verification rules, not by a larger model.
- Escalate to Opus 5.5 high only when the choice depends on subtle positioning of the contribution
  (e.g., the paper sits between theory and application venues and framing decides acceptance).
- De-escalate to Haiku 5.5 low to re-check a single fact (fee, page limit) on an official page.
- Code: none normally; scraping or tabulating many venues goes to a Haiku 5.5 subagent via the Agent tool
  (`model: "haiku"`), with results reviewed.

## Workflow
1. Extract the paper profile: topic keywords, contribution type, length, evidence type.
2. Build a shortlist (from memory candidates and the user's ideas, plus searched options).
3. For each venue, verify on official pages: aims and scope, article types and limits, review model,
   open-access options and APCs, author guidelines, AI-use policy. Use indexing sources (e.g., the publisher's
   page, Clarivate/Scopus listings when accessible) for indexing and metrics; record source URL and date.
   Never state impact factor, quartile, or acceptance rate from memory.
4. Check predatory red flags using [references/venue-checklist.md](references/venue-checklist.md).
5. Compare in a table: fit, metrics (with source/date or "unverified"), review time (official or labeled as
   reported by authors), cost, OA, risks. Give a recommendation with reasons and a backup option.
6. Submission checklist for the chosen venue; hand off the cover letter to scientific-writing.
7. Record the chosen venue in project-context.md and the decision in decisions-log.md.

## Honesty and verification rules
- Every metric, fee, limit, and policy has a source URL and access date, or is marked "unverified".
- Distinguish official numbers from author-reported estimates.
- If a venue cannot be verified as legitimate, say so; do not recommend it.

## Output format
Chat comparison (Vietnamese) for small shortlists; a docx report (via the `docx` skill) when the user wants
to keep or share it. Include the comparison table, recommendation, backup, and submission checklist.
Write back to project memory: chosen venue and key verified requirements -> project-context.md;
decision with alternatives -> decisions-log.md; facts still to verify -> open-questions.md.

## Handoffs
- Before: research-critique (is the paper ready?), scientific-writing.
- After: scientific-writing (template formatting, cover letter), research-integrity (pre-submission checklist).

## Quality checklist
- [ ] Reply in Vietnamese; memory checked first.
- [ ] Scope fit verified on official pages.
- [ ] Every metric sourced and dated, or marked unverified.
- [ ] Predatory red flags checked.
- [ ] Recommendation plus backup; submission checklist present.
- [ ] Venue recorded in project-context.md.
