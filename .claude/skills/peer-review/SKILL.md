---
name: peer-review
description: >-
  Two modes. (a) Reviews someone else's manuscript as a journal or conference referee: summary, significance, soundness, clarity, ranked comments, recommendation, and confidential comments to the editor. (b) Analyzes reviewer comments on the user's own paper and plans the revision: classifies each comment, decides accept, partially accept, or rebut with evidence, maps changes to the manuscript, and drafts the point-by-point response letter via scientific-writing (docx by default, LaTeX if the journal template requires it). Use whenever the user is asked to review a paper, received a decision letter or reviewer comments, needs a revision plan, or must write a rebuttal, e.g. "I got major revisions from T-ITS", "help me answer reviewer 2", "write my review of this manuscript", "plan the revision", including the same requests written in Vietnamese.
model: claude-opus-5-5
effort: high
---

# Peer Review

Reply to the user in Vietnamese. Keep technical terms and math notation in standard English/LaTeX.

## Purpose
Mode (a): write a constructive, specific, evidence-based referee report.
Mode (b): turn reviewer comments into a revision plan and a response letter that addresses every point
with action or evidence.

## When to use / When NOT to use
Use for: refereeing manuscripts; handling decision letters and reviewer comments.
Do NOT use for:
- Self-critique before submission -> research-critique.
- Polishing the final response letter wording only -> scientific-writing.

## Inputs to confirm before starting
Check project memory first: research-state.md (paper status), decisions-log.md, notation-and-conventions.md,
verified-references.md, project-context.md (venue).
Mode (a): the manuscript, the venue's reviewer guidelines and form (verify by search if named),
confidentiality constraints, deadline.
Mode (b): the full decision letter and all comments verbatim, the submitted manuscript, the deadline,
whether the journal requires a template (Word or LaTeX) for the response.

## Model & Effort
- Recommended model: Claude Opus 5.5 (`claude-opus-5-5`)
- Effort: high
- Rationale: A referee report must judge soundness and significance fairly; a revision plan decides which
  criticisms to accept or rebut, which directly determines acceptance. Misreading a comment or rebutting
  without evidence is costly. This judgment justifies the maximum configuration.
- Escalate: already at maximum.
- De-escalate to Sonnet 5.5 medium for tracking revision status, formatting the response letter, or
  checking that every comment has an entry.
- Code: new analyses requested by reviewers are planned with experiment-and-validation and implemented by a
  Haiku 5.5 subagent via the Agent tool (`model: "haiku"`); review results before citing them in the response.

## Workflow
### Mode (a): reviewing a manuscript
1. Respect confidentiality: do not share or upload the manuscript beyond this session; do not search for
   it by title to identify authors in double-blind review.
2. Read fully; summarize the paper in your own words (claims, method, evidence).
3. Assess significance, novelty (against verified literature), soundness (math, experiments, statistics),
   clarity, and reproducibility, using research-critique's checklist.
4. Ranked comments: major, then minor, each specific and actionable with location.
5. Recommendation with justification consistent with the comments; confidential comments to the editor.
6. Use [references/review-and-response-templates.md](references/review-and-response-templates.md).

### Mode (b): revising your paper
1. Number every comment (R1.1, R1.2, ...), quote verbatim.
2. Classify: correctness, missing experiment, missing reference, clarity, scope, misunderstanding, editorial.
3. Decide per comment: accept / partially accept / rebut with evidence. Flag comments where reviewers conflict.
4. Revision plan: action, location, owner, effort, needed analyses (handoffs to theory-and-proof,
   experiment-and-validation, literature-review).
5. Draft the response letter: hand off to scientific-writing (docx by default via the `docx` skill;
   LaTeX if the journal template requires it), with the response drafted at Opus high.
6. Final check: every comment answered; every claimed change exists in the manuscript; tone courteous.

## Honesty and verification rules
- Never claim a change was made unless it exists in the revised manuscript.
- Rebuttals rely on data, derivations, or verified references, never on assertion.
- In mode (a), do not speculate about authors' identity; base novelty claims on verified prior work.
- If a reviewer is right about a serious flaw, say so plainly to the user.

## Output format
Mode (a): referee report document (docx via the `docx` skill or the venue's form text).
Mode (b): revision plan table and response letter (via scientific-writing).
Write back to project memory: paper status (e.g., "major revision, due YYYY-MM-DD") -> research-state.md;
revision decisions -> decisions-log.md; new verified references -> verified-references.md; unresolved
reviewer points -> open-questions.md. In mode (a), store nothing about the confidential manuscript.

## Handoffs
- Before: journal-selection / submission (mode b); invitation to review (mode a).
- After: scientific-writing (response letter, revised text), experiment-and-validation, theory-and-proof,
  research-integrity (re-check before resubmission).

## Quality checklist
- [ ] Reply in Vietnamese; memory checked first (mode b).
- [ ] Every comment numbered, classified, and answered.
- [ ] Decisions backed by evidence; conflicts between reviewers flagged.
- [ ] Response letter routed via scientific-writing in the right format.
- [ ] Mode (a): confidentiality respected; recommendation consistent with comments.
