---
name: literature-review
description: >-
  Plans and runs literature reviews (narrative, systematic, scoping, survey) with a reproducible search log, screening with logged exclusion reasons, an extraction table, thematic synthesis, quality appraisal, and verified references; delivers a document (docx by default, LaTeX for thesis chapters or survey papers). Uses deep-research for candidate discovery and verifies every reference exists. Use whenever the user wants to find papers, survey a topic, write related work or a state-of-the-art chapter, check what exists on a method, or build a reading list, e.g. "find papers on MPC for Ackermann vehicles", "related work for my paper", "literature review chapter", "what has been done on X", "survey of trajectory tracking", including the same requests written in Vietnamese.
model: claude-sonnet-5-5
effort: high
---

# Literature Review

Reply to the user in Vietnamese. Keep technical terms and math notation in standard English/LaTeX.

## Purpose
Produce a literature review that another researcher could reproduce and trust: a documented search,
explicit screening decisions, a structured extraction of each paper, and a synthesis organized by
themes rather than a paper-by-paper list. Every reference is verified to exist.

## When to use / When NOT to use
Use for: related work, thesis background chapters, surveys, reading lists, "what exists on X".
Do NOT use for:
- Deciding whether a specific gap is real or novel -> research-gap (it consumes this skill's output).
- Explaining one concept or derivation -> theory-and-proof.
- Polishing the prose of an existing related-work section -> scientific-writing.

## Inputs to confirm before starting
Check project memory first: project-context.md (topic, venues, citation style), verified-references.md
(already-verified papers), decisions-log.md (scope decisions), research-state.md (current RQs).
Then confirm only what is missing:
1. Narrow topic and the question the review must answer.
2. Review type: narrative, systematic, scoping, or survey.
3. Time window and languages.
4. Inclusion/exclusion criteria (e.g., vehicle model type, validation type, venue quality).
5. Intended use: thesis chapter, related-work section, survey paper, personal reading list.
6. Papers the user already has (ask for PDFs; note paywalled databases are not accessible to Claude).
7. Citation style and output format (from memory or the user).

## Model & Effort
- Recommended model: Claude Sonnet 5.5 (`claude-sonnet-5-5`)
- Effort: high
- Rationale: A review involves many searches, careful screening, and synthesis across dozens of papers.
  Sonnet at high effort keeps the long, structured workflow accurate without Opus cost; the hardest
  judgment (is a gap real?) is deliberately handed to research-gap, which runs on Opus.
- Escalate to Opus 5.5 high when synthesis requires adjudicating contradictory theoretical results
  (e.g., conflicting stability claims) or when the review itself is a survey paper whose taxonomy is the
  contribution.
- De-escalate to Sonnet medium for a quick reading list, or to Haiku for reformatting a bibliography.
- Code (e.g., deduplicating a large export, building PRISMA counts) goes to a Haiku 5.5 subagent via the
  Agent tool (`model: "haiku"`); review its output before use.

## Workflow
1. **Scope.** Write a one-paragraph scope: question, review type, window, criteria, intended use.
2. **Search strategy.** Build Boolean queries with synonyms and variants (see
   [references/search-and-screening.md](references/search-and-screening.md)). List the sources to cover:
   Google Scholar, arXiv, IEEE Xplore / publisher sites (metadata pages), Semantic Scholar, etc.
3. **Candidate discovery: invoke the built-in `deep-research` skill** (listed as `deep-research` or
   `anthropic-skills:deep-research`). Load its SKILL.md first and pass it the scope and query set.
   If deep-research is unavailable, run the searches yourself with WebSearch/WebFetch and say so.
   Treat its output as candidates only: never accept a reference from it without verifying it exists.
4. **Verify existence** of every candidate (DOI resolver, publisher page, arXiv, indexing page). Drop or
   flag anything that cannot be found; never repair metadata by guessing.
5. **Citation chasing.** Backward (reference lists) and forward (cited-by) for the key papers.
6. **Search log.** Record every query: query string, source, date, hits, kept. Keep it reproducible.
7. **Screening.** Title/abstract, then full text where available. Log an exclusion reason for each
   excluded paper. Invite the user to upload PDFs that are paywalled.
8. **Extraction table.** One row per included paper: problem, assumptions, method, results,
   limitations, source reliability (see [references/extraction-and-synthesis.md](references/extraction-and-synthesis.md)).
   If the user wants a spreadsheet, build it with the `xlsx` skill.
9. **Thematic synthesis.** Group by themes: consensus, contradictions, trends, open problems. Do not write
   a paper-by-paper list.
10. **Quality appraisal.** Rate evidence strength per theme (validation type, reproducibility, venue).
11. **Build the document.** Default: load the `docx` skill and build the review document.
    For thesis chapters or survey papers, hand off to scientific-writing for the LaTeX route.
12. **Handoff.** When the extraction table is complete, invoke research-gap with it.

## Honesty and verification rules
- Only verified papers appear as references. Unverified items are listed separately as "unverified".
- Never invent results, numbers, or claims for a paper you could only see the abstract of; mark
  "abstract only" in the extraction table.
- State coverage limits explicitly: databases not accessible, languages excluded, cut-off date.
- "Not found in my search" is never stated as "does not exist".
- Paraphrase; do not copy abstracts into the synthesis.

## Output format
Document (docx by default; LaTeX for thesis chapters/surveys via scientific-writing) with sections:
1. Scope and review question  2. Search strategy and search log  3. Screening summary (counts, exclusion reasons)
4. Extraction table  5. Thematic synthesis  6. Quality appraisal  7. Coverage limits
8. References in the requested style (verified only) + list of unverified candidates.
Chat reply (Vietnamese): key findings in a few lines, the file, and the end-of-answer block.
Write back to project memory:
- Newly verified references -> verified-references.md (with how/when verified).
- Scope and criteria decisions -> decisions-log.md.
- Unresolved questions (e.g., papers to obtain) -> open-questions.md.

## Handoffs
- Before: research-collaboration (scoping), research-roadmap (planning).
- After: research-gap (always offer), scientific-writing (related-work section or chapter).

## Quality checklist
- [ ] Reply in Vietnamese; project memory checked first.
- [ ] Search log complete and reproducible (query, source, date, hits, kept).
- [ ] Every reference verified; unverified ones separated.
- [ ] Exclusion reasons logged.
- [ ] Synthesis is thematic, with contradictions stated.
- [ ] Coverage limits stated.
- [ ] deep-research step used (or fallback stated); output delivered as a file.
- [ ] verified-references.md updated.
