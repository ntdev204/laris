# Search strategy and screening

## Building queries
1. Split the question into 2-4 concepts (e.g., vehicle model, control method, property, validation).
2. For each concept list synonyms, abbreviations, spelling variants:
   - Vehicle: "Ackermann" OR "car-like robot" OR "bicycle model" OR "front-wheel steering" OR "autonomous vehicle"
   - Method: "model predictive control" OR MPC OR "nonlinear MPC" OR NMPC
   - Property: stability OR "recursive feasibility" OR "Lyapunov"
3. Combine: (concept A synonyms) AND (concept B synonyms) [AND ...]. Add NOT terms only with a logged reason.
4. Adapt syntax per source (Google Scholar has limited Boolean support; arXiv uses field prefixes).
5. Record every query in the search log, including ones that returned nothing useful.

## Sources
- Open: Google Scholar, arXiv, Semantic Scholar, publisher abstract pages, DBLP, OpenAlex.
- Often paywalled for full text: IEEE Xplore, ScienceDirect, SpringerLink, Scopus, Web of Science.
  Claude can usually read metadata and abstracts only; ask the user to upload PDFs.

## Search log template
| # | Date | Source | Query | Filters | Hits | Screened | Kept | Notes |
|---|---|---|---|---|---|---|---|---|

## Citation chasing
- Backward: reference list of each key paper.
- Forward: "cited by" lists (Google Scholar, Semantic Scholar).
- Stop when new rounds add no new relevant papers (record the stopping point).

## Screening
Stage 1 title/abstract, stage 2 full text. For systematic or scoping reviews, report counts in a
PRISMA-style flow (identified, duplicates removed, screened, excluded with reasons, included).
Standard exclusion reasons: out of scope; wrong vehicle model; no validation; duplicate/extended version;
not peer reviewed (if required); language; full text unavailable (flag, do not silently drop).

## Verification of existence
A reference is verified only when at least one of these is checked in the session:
DOI resolves to the same title; publisher page with matching authors/year/venue; arXiv page; indexing record.
Record method and date in verified-references.md.
