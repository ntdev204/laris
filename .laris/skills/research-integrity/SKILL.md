---
name: research-integrity
description: >-
  Checks research and manuscripts for integrity issues and produces a pre-submission integrity checklist: plagiarism and self-plagiarism (text recycling) avoidance, authorship and contribution statements (e.g., CRediT), data and code availability, image and data manipulation rules, conflicts of interest, ethics approval, disclosure of AI assistance according to the venue's verified policy, and citation hygiene. Does not give legal advice. Use whenever the user prepares a submission, reuses text from earlier papers or a thesis, decides authorship order, writes data availability or AI-use statements, or worries about plagiarism or ethics, e.g. "can I reuse my conference paper text?", "how do I disclose that I used Claude?", "who should be co-author?", "pre-submission integrity check", including the same requests written in Vietnamese.
model: claude-sonnet-5-5
effort: high
---

# Research Integrity

Reply to the user in Vietnamese. Keep technical terms and math notation in standard English/LaTeX.

## Purpose
Prevent integrity problems before submission and make required disclosures accurate and complete,
following the specific venue's and institution's verified policies.

## When to use / When NOT to use
Use for: pre-submission checks, text reuse questions, authorship, disclosures (data, code, COI, AI use),
ethics approval questions, citation hygiene.
Do NOT use for:
- Legal questions (copyright disputes, contracts, patents): say it is not legal advice and suggest the
  institution's research office or a lawyer.
- Scientific soundness review -> research-critique.

## Inputs to confirm before starting
Check project memory first: project-context.md (venue, institution, advisor), research-state.md,
decisions-log.md, verified-references.md.
Then confirm: target venue (to look up its policies), institution rules the user knows of, contributors and
their roles, prior publications overlapping this work (conference version, thesis), data/code status,
how AI tools were used in the work.

## Model & Effort
- Recommended model: Claude Sonnet 5.5 (`claude-sonnet-5-5`)
- Effort: high
- Rationale: Integrity checks are mostly systematic and policy-driven, which Sonnet handles well, but they
  require careful reading of venue policies and of the manuscript to catch overlap, missing disclosures, and
  citation problems; high effort keeps that thorough. Policy lookups, not deep novel reasoning, dominate.
- Escalate to Opus 5.5 high for genuinely ambiguous cases with serious consequences (suspected data
  manipulation by a collaborator, contested authorship), while still not giving legal advice.
- De-escalate to Sonnet medium for re-running the checklist after fixes.
- Code: overlap checks between the manuscript and the user's earlier texts (local similarity scripts) go
  to a Haiku 5.5 subagent via the Agent tool (`model: "haiku"`); note that this is not a substitute for the
  venue's official similarity check.

## Workflow
1. Look up the venue's verified policies (author guidelines, ethics, AI-use, data availability, text reuse);
   cite URLs and dates. If not found, say so.
2. Run the checklist in [references/integrity-checklist.md](references/integrity-checklist.md).
3. Text reuse: identify overlap with the user's prior work (conference paper, thesis, preprint); recommend
   disclosure and citation as the venue's policy requires; rewrite or cite as needed.
4. Authorship: apply the venue's criteria (e.g., ICMJE-style or CRediT roles if the venue uses them);
   draft the contribution statement from roles the user states.
5. Disclosures: draft data/code availability, COI, funding, ethics, and AI-use statements consistent with
   policy and with what actually happened.
6. Citation hygiene: every citation verified, cited for what it shows, no citation padding or coercive
   self-citation, quotes marked.
7. Deliver the checklist with pass/fix/unknown for each item.

## Honesty and verification rules
- Policies are quoted only from verified official pages; otherwise "unverified".
- AI-use disclosure describes the real use (e.g., drafting, editing, code), never minimized.
- Not legal advice; say so when legal questions arise.
- Do not help conceal overlap, manipulation, or undisclosed conflicts; explain the correct path instead.

## Output format
Pre-submission integrity checklist (docx via the `docx` skill or chat for short checks) plus drafted
statements. Chat reply (Vietnamese) with items needing action.
Write back to project memory: authorship and disclosure decisions -> decisions-log.md; unresolved policy
questions -> open-questions.md; verified venue policy facts -> project-context.md.

## Handoffs
- Before: scientific-writing, journal-selection, peer-review (resubmission).
- After: submission; scientific-writing (to insert statements).

## Quality checklist
- [ ] Reply in Vietnamese; memory checked first.
- [ ] Venue policies verified with URLs and dates.
- [ ] Text reuse identified and handled per policy.
- [ ] Authorship and contribution statement based on stated roles.
- [ ] Data/code, COI, funding, ethics, AI-use statements drafted.
- [ ] Citations verified; no legal advice given.
