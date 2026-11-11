# LaTeX route

## 1. Class and template
- Use the venue's official class/template when the user supplies it or when it is verified from the
  venue's author guidelines (examples of families: IEEEtran, Elsevier elsarticle, Springer, ACM acmart).
- Never guess a class option or package option. If the exact option (e.g., journal vs. conference mode,
  review/anonymous mode) is not verified, say so.
- If nothing is verified: `\documentclass[11pt]{article}` with a top comment `% TEMPORARY CLASS - replace with venue template`.

## 2. Project structure
```text
paper/
  main.tex            % preamble, format spec block as comment, \input of sections
  references.bib      % verified entries only; unverified marked % UNVERIFIED
  sections/           % one file per section for long manuscripts (intro.tex, method.tex, ...)
  figures/            % vector PDF/EPS preferred; source scripts kept in the code repo
  README.md           % compile instructions and toolchain versions
```
- Citation keys: one consistent scheme (e.g., `lastnameYYYYword`), never changed after first use.
- Citation style from the format spec block (.bst for BibTeX, or biblatex style), not chosen ad hoc.

## 3. Math conventions
- Numbered equations only for those referenced later; `\label{eq:...}` prefixes: eq:, fig:, tab:, sec:, thm:.
- Theorem-like environments as specified by the venue or the format spec block.
- Notation must match notation-and-conventions.md; units via a consistent macro or siunitx if allowed.

## 4. Compile check (Haiku 5.5 subagent, Agent tool, model: "haiku")
Subagent prompt essentials:
- Run `latexmk -pdf -interaction=nonstopmode main.tex` (or the venue's engine), capture the log.
- Report: errors, undefined references/citations, overfull/underfull boxes > 1pt, missing figures, page count.
- Fix only mechanical issues (missing packages, typos in labels); report anything touching content.
- Return the final log summary and the PDF path.
Parent then inspects the PDF with the `pdf` skill (first page, figures, references, last page) and checks limits.
If latexmk/pdflatex is not found, report it and give the exact commands:
`latexmk -pdf main.tex` or `pdflatex main && bibtex main && pdflatex main && pdflatex main`.

## 5. Venue-limit checks on the PDF
Page count (with/without references as the venue counts them), abstract word count, keywords,
figure/table counts, anonymization (author names, acknowledgments, self-citations in first person,
PDF metadata, file names).

## 6. Bibliography verification
Each entry: verified title, authors, venue, year, DOI/URL. Unverified entries:
`% UNVERIFIED: could not confirm DOI/venue on YYYY-MM-DD` above the entry, and listed in the final report.
