# T283 — Subject-aware contradiction search and the check misses of T172

Date measured: 2026-11-27. Measured by LARIS on this machine (CPU only; no model, no GPU, nothing trained or tuned).
This measures **the vocabulary rules of the write gate and the answer check** on a labelled fixture and on a rebuilt
STEM snapshot. It is not a qualification: the model and the system are **NOT QUALIFIED**.

## What changed (`crates/laris-brain/src/text.rs`, `answer.rs`)

- **Subject first.** The contradiction search compares the subject of the two statements before polarity, opposite
  words or numbers. The subject comes from the statement's form: a `term:` or `name |` label (numbers included,
  `Type 1 error:`), a leading condition (`When r is positive,`), or the words before the predicate, a number, `=`, a
  negation, a hedge or an opposite word. Words split at whitespace, so `step-up` and `step-down` stay different. When
  the form shows no subject (longer than 12 words, or nothing ends it), the search falls back to the earlier rule. Two
  statements whose subjects both show and differ never conflict.
- **Directed opposite words.** An opposite word counts only with the content word it governs (`increases voltage`
  against `decreases voltage`), and only when the other statement does not also say the first. A statement that holds
  both words (`increases voltage and decreases current`) no longer opposes one that holds either, and two identical
  statements never conflict.
- **One quantifier and hedge rule** (`text::hedge_change`) for the gate's support check and the answer check: no
  quantifier or hedge added (`always`, `all`) or dropped (`may`, `some`).
- **One clause rule** (`text::uncovered_clause`) for both checks: every clause (split at `,` `;` `:` and `and`, `but`,
  `or`, `while`, `whereas`, `which`, `because`, `so`, `thus`, `therefore`) must reach the coverage bar, not only the
  whole statement.
- Thresholds unchanged (gate 0.9 / 0.5 / 10, answer 0.8: the deployed, untuned values).

## Fixture (`crates/laris-brain/tests/fixtures/check-precision.json`, test `tests/precision.rs`)

69 cases: 22 false Conflicts of the T277 snapshot, 19 real contradictions (3 real disagreements between books found in
the snapshot, the 7 seeded pairs of T165, 9 T277 statements changed to contradict), 11 gate support cases (the two T172
strengthened proposals, constructed hedge and clause cases, book statements that must stay accepted) and 17 answer
check cases (every scripted and recorded rewording of T172, two constructed). The labels are the agent's reading.

| Measure | Before (`main` 7832575a) | After |
|---|---|---|
| Real contradictions found | 19 / 19 | **19 / 19** (none lost) |
| False Conflicts raised (T277 pairs) | 22 / 22 | **4 / 22** |
| Gate: unsupported statements accepted | 4 / 5 (both T172 strengthened claims) | **0 / 5** |
| Gate: supported statements refused | 0 / 6 | 1 / 6 |
| Answer check: unfaithful rewordings kept | 2 / 9 | **0 / 9** |
| Answer check: faithful rewordings kept | 3 / 8 | 3 / 8 |

Remaining false Conflicts: the difference comes after `is` (dependent and inconsistent systems), `N(0,1)` reads as the
decimal 0.1, a constant's condition is in parentheses (Sackur-Tetrode at two pressures), and `no ... motion` against
`motion ceases` reads as a polarity flip. The new false refusal: a quote wider than the statement whose other sentence
holds a hedge (`It may cause bleeding.`), because the hedge rule reads the whole quote; a proposer can quote the one
sentence. Faithful paraphrase that changes words (`lowers` for `reduces`) is still refused, as before; the Claim's own
wording is then used.

## T172 measures again (`reports/brain/T283-cognitive-rerun.json`, same configuration, Qwen recording included)

| Advisor | Rewordings kept that were unfaithful (T172 → now) | Unsupported proposals accepted by the gate (T172 → now) |
|---|---|---|
| hallucinating-scripted | 2 / 5 → **0 / 5** | 0 / 4 → 0 / 4 |
| overconfident-scripted | 0 / 5 → 0 / 5 | 2 / 2 → **0 / 2** |
| corrupting-scripted | 0 / 4 → 0 / 4 | 0 / 1 → 0 / 1 |
| Qwen3.5-9B (recorded) | 0 / 0 → 0 / 0 | 0 / 4 → 0 / 4 |

Faithfulness of the sentences read is 1.0 for every advisor; no unsupported reply reached the user in the loop. The
T172 report itself is kept unchanged as the measured evidence of that date.

## STEM snapshot rebuilt by the T277 procedure

`python scripts/build_stem_brain.py build NAME` from the same pinned inputs (`configs/stem-brain.json` `191d67b1…`,
`provenance.json` `795f1803…`). The frozen snapshots `stem-t277-2` and `stem-t285-2` are not changed.

| Snapshot | Claims | Refused | Conflicts | Lint | B6 (13-gram, 14,524 items) | SHA-256 |
|---|---|---|---|---|---|---|
| `stem-t277-2` (frozen) | 19,925 | 0 | 585 (258 CODATA, 323 book, 4 mixed) | 0 | 0 hits | `fb01dd03…ddeacb` |
| **`stem-t283-1`** (T277 procedure; a clean-tree rebuild at `3b9a05dc` gave the same hash) | 19,925 | 0 | **104** (5 CODATA, 98 book, 1 mixed) | 0 | **0 hits** | `37f787aa…0c679d50` |
| `stem-t285-2` (frozen) | 20,380 | 0 | 668 | 0 | 0 hits | `5019e63b…a9c4` |
| `stem-t283-2` (T285 procedure, `--sources`) | 20,380 | 0 | 104 | 0 | 0 hits | `d5e1ce90…56d8fc2` |

A seeded sample of 20 of the 104 Conflicts of `stem-t283-1` (seed 283): 2 are real disagreements between the books (g
averages 9.80 or 9.81 m/s²; 92 or 98 natural elements); 18 are not (paraphrases with a word of polarity or a number,
titled boxes longer than the subject window, and different formulas under one name such as `mean µ`). In T277 the same
kind of sample held none real.

## Limits

- A rule on vocabulary and word order, not on meaning; the fixture is small and labelled by one reader, so one case
  moves a rate by 5 to 11 points.
- When the form of a statement shows no subject, the search uses the earlier rule; longer titled boxes stay exposed to
  false Conflicts.
- Subjects are compared as sets of words: word order does not matter, but a real contradiction whose two statements
  name the subject with different words (`vitamin D` and `cholecalciferol`) is missed when both subjects show.
- Changing the deployed snapshot is not part of this task; `stem-t277-2` stays the deployed and frozen one until the
  owner decides.
