---
name: research-roadmap
description: >-
  Long-term research planning and reporting: thesis or research agenda, publication pipeline, milestone plans, advisor-meeting preparation and briefs, progress reports (docx), mentoring students, transition toward independent research, and time management. Keeps research-state.md and open-questions.md current. Use whenever the user plans the next months or years, prepares for an advisor meeting, writes a progress report, organizes a publication pipeline, or feels behind schedule, e.g. "plan my PhD timeline", "prepare a brief for my meeting with my advisor", "write my semester progress report", "what papers can I get out of my thesis?", "how do I plan my postdoc agenda?", including the same requests written in Vietnamese.
model: claude-sonnet-5-5
effort: high
---

# Research Roadmap

Reply to the user in Vietnamese. Keep technical terms and math notation in standard English/LaTeX.
Reports are written in the language the advisor or institution requires (record it).

## Purpose
Keep the long-term plan realistic and visible, keep the advisor informed with concise documents, and keep
project memory current so every session starts from the true state of the research.

## When to use / When NOT to use
Use for: timelines, publication pipelines, advisor briefs, progress reports, mentoring plans, career
transition plans, prioritization when overloaded.
Do NOT use for:
- Designing a single study -> research-design.
- Writing papers -> scientific-writing.
- Funding applications -> grant-proposal.

## Inputs to confirm before starting
Check project memory first: research-state.md, open-questions.md, decisions-log.md, project-context.md
(stage, deadlines, advisor, report format).
Then confirm: horizon (weeks, semester, years), fixed deadlines (institutional, conferences), available
hours per week, report format required by the advisor or institution, recent progress not yet recorded.

## Model & Effort
- Recommended model: Claude Sonnet 5.5 (`claude-sonnet-5-5`)
- Effort: high
- Rationale: Planning across papers, chapters, and deadlines needs careful dependency and capacity
  reasoning, and progress reports must be accurate against memory; Sonnet at high effort is sufficient.
  The judgment is mostly organizational rather than deep scientific evaluation.
- Escalate to Opus 5.5 high for strategic decisions with large consequences (changing thesis direction,
  dropping a contribution, choosing between postdoc research agendas).
- De-escalate to Sonnet medium or Haiku low for routine status updates and reformatting a brief.
- Code: Gantt charts or schedule computations go to a Haiku 5.5 subagent via the Agent tool
  (`model: "haiku"`); or use the `xlsx` skill for tracker sheets.

## Workflow
1. Read research-state.md, open-questions.md, decisions-log.md; ask what changed since the last update.
2. Update research-state.md (done / in progress / blocked / next) with dated entries; consolidate old ones.
3. Planning: list deliverables (chapters, papers, talks), dependencies, effort estimates, buffers, and fixed
   deadlines; produce a milestone plan ([references/roadmap-templates.md](references/roadmap-templates.md)).
   Flag infeasible plans plainly and propose cuts.
4. Publication pipeline: map thesis contributions to papers and venues (venues verified via journal-selection).
5. Advisor meeting brief: progress since last meeting, results, decisions needed, questions (from
   open-questions.md), next steps; one or two pages.
6. Progress report: **build with the built-in `docx` skill** (load its SKILL.md first); follow a sample report's
   style if provided (mostly prose and bullets, few tables).
7. Mentoring or transition plans when asked: goals, skills, milestones, independence markers.
8. Update open-questions.md (add advisor questions, remove resolved ones).

## Honesty and verification rules
- Report progress exactly as it is; never inflate status.
- Estimates labeled as estimates with assumptions (hours per week).
- If the timeline is unrealistic, say so with the arithmetic.
- Venue deadlines verified on official pages.

## Output format
Roadmap or progress report .docx (via the docx skill), advisor brief (.docx or chat), optional tracker
(.xlsx via the xlsx skill). Chat reply (Vietnamese) with key changes and decisions needed.
Write back to project memory: research-state.md (status, next actions), open-questions.md (advisor questions),
decisions-log.md (planning decisions the user adopts), project-context.md (deadlines).

## Handoffs
- Before: any skill that changed the research state.
- After: research-design, journal-selection, scientific-writing, research-presentation.

## Quality checklist
- [ ] Reply in Vietnamese; memory read first and updated at the end.
- [ ] Dependencies, buffers, and fixed deadlines included; infeasibility flagged.
- [ ] Advisor brief concise with explicit decisions needed.
- [ ] Reports built with the docx skill in the required style.
- [ ] research-state.md and open-questions.md current and consolidated.
