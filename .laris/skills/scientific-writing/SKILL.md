---
name: scientific-writing
description: >-
  Writes and edits scientific documents in the format the target venue requires. Starts by recording a format spec block (venue, template, sections, limits, citation style, math conventions, submission form, output route), then routes outlines, reports, proposals, progress reports, cover letters, and Word-venue response letters to Word via the docx skill, and journal papers, conference papers, letters, thesis chapters, and supplements to LaTeX (.tex + .bib) with a compile check. Covers contribution framing, three-level editing with a change log, cover letters, and reviewer responses. Use whenever the user wants to write, draft, edit, restructure, or format any paper, chapter, report, abstract, or letter, e.g. "write the introduction", "format this for IEEE T-ITS", "draft a conference paper", "make an outline for my progress report", "polish my abstract", "convert to the journal template", including the same requests written in Vietnamese.
model: claude-sonnet-5-5
effort: medium
---

# Scientific Writing

Reply to the user in Vietnamese. Keep technical terms and math notation in standard English/LaTeX.
The document itself is written in the language recorded in the format spec block.

## Purpose
Produce documents that meet the target venue's requirements exactly and read as clear, honest academic
writing: gap -> contribution -> method -> results -> limitations, with no overclaiming.

## When to use / When NOT to use
Use for: drafting, editing, restructuring, formatting, abstracts, cover letters, response letters.
Do NOT use for:
- Deciding what the contribution is -> research-gap.
- Fixing a proof or derivation -> theory-and-proof (then come back to write it up).
- Analyzing reviewer comments and deciding what to change -> peer-review (it hands the letter back here).
- Slides and posters -> research-presentation. Grant proposals -> grant-proposal.

## Inputs to confirm before starting
Check project memory first: project-context.md (venues, citation style, LaTeX/Word preference, report style),
notation-and-conventions.md, research-state.md (contribution, paper status), verified-references.md.
Then obtain what is missing, starting with STEP 0 (the target format).

## Model & Effort
- Recommended model: Claude Sonnet 5.5 (`claude-sonnet-5-5`)
- Effort: medium
- Rationale: Most writing work (drafting sections from agreed content, editing, formatting to a template)
  is well within Sonnet at medium effort and benefits from speed across long documents.
- Escalate to Claude Opus 5.5 at high effort for: Introduction and contribution framing (positioning
  against prior work decides acceptance), and reviewer responses (tone and evidence-based rebuttal carry
  high stakes). State the escalation in the reply.
- De-escalate to Haiku 5.5 low for mechanical tasks: reference reformatting, consistent capitalization,
  converting a verified table into LaTeX.
- Code: LaTeX compilation, bibliography checks, and word/page counting are delegated to a Haiku 5.5 subagent
  via the Agent tool (`model: "haiku"`); review its logs before reporting results.

## Workflow
**STEP 0 — Target format (mandatory).**
1. Obtain the target format as input: venue name, template, author guidelines, attached files.
   - If only a name is given: search for the official author guidelines, open the official page, and
     verify each requirement; cite the URL.
   - If nothing is given: ask one short question; if the user cannot answer, use neutral IMRaD labeled
     "temporary default".
2. Fill the **format spec block** ([references/format-spec-block.md](references/format-spec-block.md)):
   paper type; language and spelling variant; required sections and order; limits (words/pages, abstract,
   figures/tables, keywords); citation style and .bst/.csl/biblatex file; math conventions; figure/table specs;
   submission form (LaTeX class or Word, double-blind, cover letter, author contributions); output route.
3. **Choose output route (docx or LaTeX) from document type and venue, record it in the format spec block.**
   - Word (.docx): research reports, project/grant proposals, outlines, progress reports, advisor-meeting
     briefs, cover letters, response letters when the venue wants Word.
   - LaTeX (.tex + .bib): journal articles, conference papers, letters, thesis chapters, supplementary material.
   - Ambiguous (thesis, response letter, cover letter): ask one short question or follow the supplied template.
   - The venue's requirement overrides these defaults; an explicit user choice overrides everything.
4. Repeat the format spec block at the top of the working document (as a comment in .tex, as a first
   section or note in docx drafts; remove from the final submission file).
5. If the venue changes later: list everything that must change (template, limits, citation style, sections,
   anonymization) and get confirmation before editing.

**STEP 1 — Read inputs.** Read provided PDFs (templates, guidelines, papers) with the built-in `pdf` skill
(load its SKILL.md first; for reading only, `pdf-reading` if listed). Collect verified references.

**STEP 2 — Plan.** Outline sections with the content of each, following
gap -> contribution -> method -> results -> limitations. Confirm the outline for long documents.

**STEP 3 — Build by route.**
- **docx route:** load the built-in `docx` skill's SKILL.md and build the file with it. Do not hand-roll
  Word XML. Follow a user-supplied template exactly.
- **LaTeX route:** write .tex/.bib directly following [references/latex-route.md](references/latex-route.md):
  verified venue class (never guess class or package options; if unverified, use `article` marked
  TEMPORARY); `main.tex`, `references.bib`, `sections/`, `figures/`, `README.md` with compile instructions;
  consistent citation keys; math conventions from the format spec block and notation-and-conventions.md.
- **Collaborative route:** only if the user asks for a shareable/collaborative document, use the built-in
  `docs` skill instead.

**STEP 4 — Compile check (LaTeX route).** If a TeX toolchain (latexmk/pdflatex) is available, delegate
compilation to a Haiku 5.5 subagent: compile, collect errors and warnings (undefined references, missing
citations, overfull boxes), fix, recompile. Then inspect the compiled PDF with the `pdf` skill (layout,
figures, references). If no toolchain is available, say so, deliver sources plus exact compile commands,
and never claim it compiled.

**STEP 5 — Venue limits.** On the compiled PDF (or docx), check page count, abstract length, word limits,
figure counts, and anonymization for double-blind review. Report every violation.

**STEP 6 — Editing passes** (when editing existing text), at the level requested:
(1) fix errors, (2) rewrite sentences, (3) restructure. Always state what changed (change log).
See [references/editing-and-letters.md](references/editing-and-letters.md) for style rules, cover letters,
and point-by-point reviewer responses.

**STEP 7 — Deliver and write back** to project memory.

## Honesty and verification rules
- Never state a venue rule that was not verified; cite the guideline URL or mark "unverified".
- Every bibliography entry is verified before it enters references.bib; unverified entries get a
  `% UNVERIFIED` comment and are listed in the final report.
- No result, number, or claim appears in the text unless it exists in the user's results or a verified source.
- No overclaiming: words like "guarantee", "optimal", "robust", "real-time" need explicit support.
- Never claim a compile succeeded unless it ran in this session.

## Output format
- Files: docx (via docx skill) or LaTeX project (main.tex, references.bib, sections/, figures/, README.md),
  plus compiled PDF when a toolchain exists.
- Chat reply (Vietnamese): the format spec block summary, what was produced, change log for edits,
  verification report (unverified references, venue-limit violations, compile status), end-of-answer block.
- Write back to project memory: chosen venue/route and citation style -> project-context.md; notation fixed
  while writing -> notation-and-conventions.md; paper status -> research-state.md; newly verified references
  -> verified-references.md; venue questions not yet resolved -> open-questions.md.

## Handoffs
- Before: research-gap (contribution), theory-and-proof, experiment-and-validation, literature-review,
  peer-review (response letter content), journal-selection (venue).
- After: research-critique (pre-submission review), research-integrity (pre-submission checklist),
  research-presentation (talk from the paper).

## Quality checklist
- [ ] Reply in Vietnamese; memory checked first.
- [ ] Format spec block complete, verified, and at the top of the working document.
- [ ] Output route chosen and recorded (docx or LaTeX).
- [ ] docx built with the docx skill; LaTeX uses a verified class or a marked temporary one.
- [ ] Compile check run via Haiku subagent and PDF inspected, or clearly reported as not run.
- [ ] Venue limits checked; violations reported.
- [ ] All references verified or marked `% UNVERIFIED` and listed.
- [ ] Change log given for edits; no overclaiming.
