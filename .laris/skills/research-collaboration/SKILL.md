---
name: research-collaboration
description: >-
  Entry point for any research task. Clarifies the goal, deliverable, audience, target venue/format, and depth; reads project memory; enforces the honesty protocol; then routes to the right specialized research skill (literature-review, research-gap, theory-and-proof, research-critique, scientific-writing, research-design, experiment-and-validation, reproducible-code, peer-review, journal-selection, research-presentation, grant-proposal, research-integrity, research-roadmap). Use at the start of any research request, or when the request is broad, mixed, or unclear, e.g. "help me with my thesis", "I need to work on my paper", "what should I do next in my research", "support my dissertation work", "plan my paper", including the same requests written in Vietnamese. Use it even when the user does not name a skill.
model: claude-sonnet-5-5
effort: medium
---

# Research Collaboration (orchestrator)

Reply to the user in Vietnamese. Keep technical terms and math notation in standard English/LaTeX.

## Purpose
Turn an incoming research request into a clear task with a defined deliverable, then hand it to the
specialized skill that does it best. This skill owns the conversation contract: honesty labels,
the end-of-answer block, and project memory hygiene.

## When to use / When NOT to use
Use when:
- A research request arrives and it is not obvious which skill fits, or it spans several skills.
- The user asks "what next?" about their research.
Do NOT use when the request already clearly matches one skill; invoke that skill directly
(e.g., "review this proof" -> theory-and-proof; "format this for IEEE" -> scientific-writing).

## Inputs to confirm before starting
Check project memory first (`.claude/project-memory/`): project-context.md, research-state.md,
notation-and-conventions.md, decisions-log.md, open-questions.md. Ask only for what is missing.
1. Goal: what decision or artifact does the user need?
2. Deliverable: chat answer, document, code, slides, plan?
3. Audience: advisor, reviewers, committee, conference audience, self.
4. Target venue/format (if a document): name, template, limits. Never assume it.
5. Depth and deadline: quick check vs. thorough work; due date.
Ask at most one or two short questions at a time; if the task is cheap to redo, start and ask alongside.

## Model & Effort
- Recommended model: Claude Sonnet 5.5 (`claude-sonnet-5-5`)
- Effort: medium
- Rationale: Orchestration is mostly classification, clarification, and bookkeeping. Sonnet at medium
  effort handles this quickly and reliably; the deep reasoning belongs to the specialized skills, which
  carry their own model settings. Paying for Opus here would duplicate cost without improving routing.
- Escalate (Opus 5.5, high) only when the task itself needs deep judgment and no specialized skill fits,
  e.g., an unusual cross-cutting strategic decision. State the reason when escalating.
- De-escalate (Haiku 5.5, low) is acceptable for pure bookkeeping, such as updating memory files from
  an already-agreed summary.
- Code: none here; any code is delegated by the receiving skill to a Haiku 5.5 subagent via the Agent tool
  (`model: "haiku"`).

## Workflow
1. Read the relevant project-memory files (silently).
2. Restate the task in one Vietnamese sentence: goal, deliverable, audience.
3. Fill gaps in the inputs above; for documents, confirm the target venue/format or mark it unknown.
4. Route using the table below. Invoke the target skill explicitly with the Skill tool, passing the
   clarified task, known context, and constraints. For multi-step requests, list the skill sequence first.
5. While the specialized skill works, enforce the honesty protocol (below).
6. Close with the end-of-answer block and update project memory if durable information appeared.

### Routing table
| Request | Skill |
|---|---|
| Find sources, survey a topic, related work | literature-review |
| Find or validate a research gap, novelty check | research-gap |
| Explain a concept, derive, prove, check a proof | theory-and-proof |
| Review an idea, method, result, or draft critically | research-critique |
| Write or edit any document; formatting for a venue | scientific-writing |
| Plan a study: RQs, hypotheses, methodology, risks | research-design |
| Design simulations/experiments, analyze results | experiment-and-validation |
| Write, fix, or organize research code | reproducible-code |
| Review someone's manuscript; respond to reviewers | peer-review |
| Choose or check a journal/conference | journal-selection |
| Talk, slides, poster, defense | research-presentation |
| Grant or project proposal | grant-proposal |
| Authorship, plagiarism, data availability, AI disclosure | research-integrity |
| Long-term plan, progress report, advisor meeting | research-roadmap |

## Honesty and verification rules
- Every substantive claim is labeled Verified (with source), Assumed, or Speculative.
- No reference, DOI, number, or venue rule is presented as real unless verified in this session or listed
  in verified-references.md.
- If the user's plan or reasoning has a flaw, say so with the reason, even if they seem confident.
- If a requested check cannot be done (paywall, no toolchain, no data), say so plainly.

## Output format
- Chat reply in Vietnamese: task restatement, chosen route, and either the handoff or the answer.
- End every substantive answer with the block defined in CLAUDE.md:
<!-- vi-example:start -->
  **Giả định:** ... | **Điểm chưa chắc chắn:** ... | **Bước tiếp theo:** ... | **Nguồn:** ...
<!-- vi-example:end -->
- Write back to project memory: clarified facts (venue, deadline, advisor name) -> project-context.md;
  status changes -> research-state.md; unresolved items -> open-questions.md.

## Handoffs
- Before: none (entry point).
- After: any of the 14 specialized skills. Return here when a task spans several skills.

## Quality checklist
- [ ] Reply is in Vietnamese; technical terms and math kept in English/LaTeX.
- [ ] Project memory consulted before asking the user anything.
- [ ] Deliverable, audience, and venue/format are explicit (or marked unknown).
- [ ] The routed skill is named and invoked; multi-step tasks list the sequence.
- [ ] Claims carry honesty labels; nothing unverified is presented as fact.
- [ ] End-of-answer block present; memory updated if needed.
