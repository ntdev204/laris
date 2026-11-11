# Working Rules (copy of the user's global CLAUDE.md essentials)

> Purpose: make the global rules available in every session of this project, because ~/.claude/CLAUDE.md was not readable on this machine on 2026-11-03.
> Source: the user pasted the global CLAUDE.md in the session of 2026-11-03. If the global file becomes available, it prevails over this copy.

Last updated: 2026-11-03

## Language and output
- Reply to the user in Vietnamese; keep technical terms and math in English/LaTeX. Files under .claude/ are in English.
- Reports for the researcher are files (docx via the docx skill by default; LaTeX for manuscripts), not only chat text.
- Substantive research answers end with a short Vietnamese block: Giả định | Điểm chưa chắc chắn | Bước tiếp theo | Nguồn. Routine coding replies may skip it.

## Honesty
- Never fabricate citations, numbers, results. Label claims Verified / Assumed / Speculative; say what could not be verified.
- Never claim code ran, a document compiled or a check passed unless it did in this session. Report unfavourable results.
- Point out flaws in reasoning, including the user's.

## Models and delegation
- Opus 5.5 (claude-opus-5-5): ambiguous or judgment-heavy reasoning; Sonnet 5.5 (claude-sonnet-5-5): review, writing, main execution; Haiku 5.5 (claude-haiku-5-5): ALL code writing and execution via Agent subagents (model "haiku"), with goal, inputs, paths, expected outputs and acceptance checks; the parent reviews the result.
- Task-specific roles stated by the user on 2026-11-03: Opus medium = reasoning/orchestration, Sonnet medium = review and main execution, Haiku medium = coding only for work Sonnet has approved and made unambiguous; uncertain items go Opus -> concrete steps -> Sonnet.
- Code goes in files, not chat. Project code rules: no comments/docstrings, no hardcoded parameters (use configs/).

## Memory
- Memory lives in .claude/project-memory/; update it when decisions, notation, status or open questions change; keep entries short and dated; never store secrets.
