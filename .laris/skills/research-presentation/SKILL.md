---
name: research-presentation
description: >-
  Builds research talks, conference presentations, posters, lab-meeting slides, and thesis defense decks: story arc, slide-by-slide outline with a time budget, figure guidance, anticipated Q&A with answer outlines, and a rehearsal checklist. Builds slides with the pptx skill and checks rendering after building; posters as pptx or PDF on request. Use whenever the user needs slides or a talk, e.g. "make slides for my conference talk", "prepare my defense presentation", "15-minute talk on my MPC paper", "poster for the workshop", "what questions will the committee ask?", including the same requests written in Vietnamese.
model: claude-sonnet-5-5
effort: medium
---

# Research Presentation

Reply to the user in Vietnamese. Keep technical terms and math notation in standard English/LaTeX.
Slides are in the language the user or event requires (record it before building).

## Purpose
Turn research into a talk the audience can follow in the time available, with slides that carry figures
and one message each, and with preparation for questions.

## When to use / When NOT to use
Use for: talks, slides, posters, defense, lab meetings, seminars.
Do NOT use for:
- Writing the paper or report -> scientific-writing.
- Progress reports to the advisor as documents -> research-roadmap.

## Inputs to confirm before starting
Check project memory first: research-state.md (results to present), notation-and-conventions.md,
project-context.md (venue, advisor), verified-references.md.
Then confirm: event type and audience, time limit (talk + Q&A), language, required template (university or
conference), slide size, source material (paper, figures), poster size if any, deadline.

## Model & Effort
- Recommended model: Claude Sonnet 5.5 (`claude-sonnet-5-5`)
- Effort: medium
- Rationale: Structuring a talk and building slides from existing, verified content is well handled by
  Sonnet at medium effort; the scientific judgment was made upstream.
- Escalate to Opus 5.5 high for a thesis defense Q&A preparation where questions probe the validity of
  the main contributions, or when the story must reconcile weak results honestly.
- De-escalate to Haiku 5.5 low for mechanical edits (fonts, numbering, swapping figures).
- Code: regenerating figures for slides goes to a Haiku 5.5 subagent via the Agent tool (`model: "haiku"`)
  using the repo's plotting scripts; review the output.

## Workflow
1. Define the one-sentence message and the audience's background.
2. Story arc: problem -> why it matters -> gap -> idea -> key result -> evidence -> limits -> takeaway.
3. Slide-by-slide outline with a time budget per slide
   ([references/talk-templates.md](references/talk-templates.md)); confirm it for long talks.
4. Figures: reuse paper figures re-styled for projection (large fonts, few curves, highlighted key result).
5. **Build the deck with the built-in `pptx` skill:** load its SKILL.md first and follow it; use the user's
   template if supplied. Posters: pptx or PDF as requested (PDF via the `pdf` skill when needed).
6. **Verify rendering after building:** render slides to images (as the pptx skill describes) and inspect
   every slide for overflow, unreadable text, broken math, and figure quality; fix and re-render.
7. Anticipated Q&A: 8-15 likely questions with answer outlines and backup slides.
8. Rehearsal checklist and timing plan.

## Honesty and verification rules
- Only results that exist in the user's work or verified sources appear on slides.
- Do not hide limitations; include them on a slide.
- Cited works on slides are verified.

## Output format
.pptx deck (and poster file if requested), plus a chat summary (Vietnamese) with outline, timing, Q&A
list, and rendering-check result.
Write back to project memory: talk date and status -> research-state.md; questions the user could not
answer well -> open-questions.md.

## Handoffs
- Before: scientific-writing (paper), experiment-and-validation (figures), research-critique (predicted questions).
- After: research-roadmap (post-talk follow-ups).

## Quality checklist
- [ ] Reply in Vietnamese; memory checked first.
- [ ] One message per slide; timing fits the slot.
- [ ] Built with the pptx skill; every slide rendered and inspected.
- [ ] Limitations slide present; Q&A prepared with backups.
- [ ] Only verified results and references.
