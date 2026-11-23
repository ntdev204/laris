# T277 — Verified STEM knowledge in the main brain: the snapshot, its leakage scan and retrieval

Date measured: 2026-11-23. Measured by LARIS on this machine (CPU only; no model, no GPU). Development splits only for
retrieval; the leakage scan reads every benchmark item (dev and sealed, from the raw files, as the T275 scan does) and
reports ids and hashes only. This measures the **brain snapshot**, not the system: the model (Qwen3.5-4B) and the
system are **NOT QUALIFIED**. No item text is reproduced here.

## Snapshot

| | |
|---|---|
| Name and folder | `stem-t277-2`, `data/brain/snapshots/stem-t277-2/` (outside Git) |
| **Snapshot SHA-256** | `fb01dd0369977487c4bcebd8f8ae2f627031fc9ebe0630029f37467c48ddeacb` (SHA-256 over every file's path and hash, `laris-server brain freeze`); a second build from the same inputs gave the same hash |
| Code | revision `27cfbb75` (clean tree), `configs/stem-brain.json` SHA-256 `191d67b1…3acc17`, `provenance.json` `795f1803…825e6d` |
| Gate | the deployed server's thresholds (min support 0.9, equivalence 0.6, subject overlap 0.5, search depth 10, 100,000 bytes); notes dated 2026-11-23 |
| Size | 23,253 files, 121 MB; build about 4.5 min (proposals with solver runs, gate import, freeze) |
| Lint | 0 problems (`lint_brain` over the whole vault) |

Sources, at the pins of `configs/stem-brain.json` (owner decision 2026-11-23: the live STEM editions are CC BY-NC-SA
4.0, so each book is taken from the newest git commit at which it was CC BY 4.0; licence checked in every collection
file, identity checked against the openstax.org catalogue by title and `cnx_id`):

| Book | Modules | Book | Modules |
|---|---|---|---|
| University Physics Vol. 1 / 2 / 3 | 124 / 119 / 95 | Intermediate Algebra 2e | 83 |
| College Physics 2e | 283 | Introductory Statistics 2e | 102 |
| Physics | 100 | Statistics | 101 |
| Chemistry 2e / Atoms First 2e (shared modules) | 149 / 149 | Biology 2e | 259 |
| College Algebra 2e / Algebra and Trigonometry 2e / Precalculus 2e (shared) | 69 / 94 / 87 | Concepts of Biology | 107 |
| Microbiology | 159 | Astronomy 2e | 199 |
| Introduction to Python Programming | 115 | NIST CODATA 2022 (table, SHA-256 `77fb90e6…3f67e67`) | 1 Source, 355 constants |

## What the gate accepted

| Notes | Count |
|---|---|
| Sources (`document`) | 2,136: 2,135 OpenStax (2,133 modules; one glossary cut into three parts to stay below 100,000 bytes) and 1 CODATA |
| Sources (`tool_run`, solver calls) | 606 |
| Claims | 19,925, all at level `sourced`: 7,986 glossary definitions, 8,990 key concepts and summary sentences, 1,169 key-equation rows, 1,425 boxed statements with their formula (a titled box, or an untitled formula box with the paragraph before it that states its condition), 355 constants |
| Claims with a solver link (`solver_ref`) | 691, to 606 solver runs: 361 `verified` (CODATA lookups and a few formulas), 245 `proposal` (symbolic `solve` of a formula for its left side: substitution checked, completeness not checkable; the link records that status and is not evidence) |
| Refused | 0 Sources, 0 Claims |
| Conflicts | 585 (848 Claims in one): 258 among CODATA constants, 323 among book Claims, 4 mixed |

- Ten whole modules of exercises are left out by title (`module_titles_left_out`): review exercises, practice tests
  and final exams, solution sheets and two lab sheets of each statistics book. A first final build (`stem-t277`) still
  held them, because their sections carry no exercise class; it was replaced before any use.
- Every Source note begins with its provenance: source and place in the book(s), repository and commit, file and its
  SHA-256, licence with attribution, and what the conversion left out (exercises, review and practice sections,
  teacher notes, learning objectives, media). Every Claim is a line of its Source, so its quote and span are exact.
- No Claim is above `sourced`: corroboration across OpenStax books was not proposed (the books share a publisher and
  reuse text, so they are not independent), and no tool run reproduces a textbook statement.
- **Conflicts are mostly false.** A seeded sample of 20 book Conflicts held no real contradiction: they pair contrasts
  (sulfite and sulfate, Type I and Type II error, leptons and hadrons) or paraphrases. The CODATA Conflicts pair
  different constants with similar names and the same unit ("electron mass energy equivalent in MeV" and "muon mass
  energy equivalent in MeV"). The cause is the vocabulary rule of the contradiction search (shared content words plus
  a negation, an opposite word or a different number with the same unit), which reads words, not subjects. Both sides
  stay in the brain; nothing was removed.

## Leakage scan (gate B6)

| | |
|---|---|
| Items scanned | 14,524 (MATH-500, MATH train, MMLU-Pro STEM test and validation, GPQA main and Diamond), questions and options |
| n-gram | 13 words (`configs/stem-benchmarks.json`) |
| **Hits on the snapshot** | **0** |
| Left out by the build | 11 text blocks in 8 modules (and the statements in them) |

The first build of the same books had 38 hits in 7 passages that benchmark items repeat almost word for word (Kepler's
first law, the general form of a conic, the notation of the rational zero theorem, the definition of glycolysis, the
collinear-points test); none was a copied question. The build now leaves out every block that shares a 13-word
sequence with any benchmark item, alone or across neighbouring blocks, and says so in the Source's provenance lines.
This only removes text; no benchmark text enters the brain.

## Retrieval on the development splits

The pipeline's retrieval (`laris-server brain retrieve`, the server's `MainBrain` source, fused scorer), queried with
the question and its options. No relevance labels exist, so recall is measured by a proxy: for a multiple-choice item
whose correct option is words (no digits), whether one of the top-k passages holds every content word of that option;
the same rate over the wrong options is the comparison.

| Benchmark (dev) | Items | Eligible | k | Correct option supported (Wilson 95 %) | Wrong options supported |
|---|---|---|---|---|---|
| MMLU-Pro STEM | 1,175 | 299 | 1 | 10.4 % (7.4-14.3) | 7.5 % |
| | | | 5 | 17.1 % (13.2-21.7) | 11.9 % |
| | | | 10 | **21.1 %** (16.8-26.0) | 14.4 % |
| GPQA (main − Diamond) | 250 | 78 | 1 | 5.1 % (2.0-12.5) | 3.5 % |
| | | | 5 | 5.1 % (2.0-12.5) | 5.0 % |
| | | | 10 | 6.4 % (2.8-14.1) | 6.0 % |
| MATH | 500 | 0 | — | not measurable by this proxy (answers are numbers or expressions) | — |

Every item got passages (1,925 of 1,925).

## Reading

- The snapshot meets the task's checks: every note came through the gate with provenance, lint is clean, B6 has 0
  hits, and the snapshot has one hash that a rebuild reproduces.
- Retrieval leans towards the correct option on MMLU-Pro STEM (21.1 % against 14.4 % at k = 10) and gives no signal
  on GPQA (6.4 % against 6.0 %, within noise on 78 items), as expected for a set built so that search does not help (ADR-026 section 1). The
  proxy says nothing about whether an answer improves; that is measured with the router and harness in T278.
- Open for the owner: (1) the false Conflicts (585, 848 Claims) come from the vocabulary rule of the contradiction
  search; a subject-aware rule or a reviewed list would be a change to the brain's gate (programme 3); (2) Claims stay
  at `sourced`; raising them needs independent corroboration or a tool check that reproduces the statement.
- Owner decision 2026-11-23: (1) goes to T283 (programme 3); (2) Claims stay at `sourced`, which the deployed decider
  requires to answer.
