# T206: pair-task data corrections from the T193 audit

Applied 2026-11-15 by `scripts/correct_pair_data.py --apply`. Every figure comes from
`reports/verification/T206-pair-data-corrections.json`; the rebuild of the similarity table is recorded in
`reports/verification/T206-sts-extra-rebuild.json`. Data was read and written only. Nothing was trained, no tokenizer
was fitted and no model was scored. The foundation model is **NOT QUALIFIED**.

Owner decisions (2026-11-15):
- Keep SICK, rebuilt from `relatedness_score` and marked by source.
- Remove the duplicated SQuAD v1 training rows rather than re-split SQuAD 2.0, so the SQuAD validation and test splits
  that G06 and G07 use stay unchanged.

## 1. Similarity: `sts_extra_en`

**Precheck.** Every SICK-EN row of the old table was matched to the raw SICK files (9,840 rows) by its normalised,
unordered sentence pair [`sick.precheck_current_table`]. All 8,389 SICK rows had a stored score equal to the SICK NLI
`label` divided by 5. 51 and 256 rows also equalled a relatedness-based value, but only by coincidence of values (for
example label 1 / 5 = 0.2 = relatedness 1 / 5). This confirms the T193 finding.

**Cause and fix.** `scripts/check_sts_leakage.py` picked the first present column of `("score", "label",
"relatedness_score")`. It now reads the column and native range each source declares in
`configs/data/english_sources.yaml`, and refuses a similarity source that declares none:

| Source | Score column | Native range | Mapping |
|---|---|---|---|
| STS Companion | `label` | 0 to 5 | s / 5 (unchanged) |
| STS12 train | `score` | 0 to 5 | s / 5 (unchanged) |
| SICK-EN | `relatedness_score` | 1 to 5 | (r - 1) / 4 |

SICK relatedness 1 means unrelated, which is STS 0, so the SICK range is mapped from 1, not divided by 5. The mapping is
configuration: changing `score_range` changes it.

**Postcheck** [`sick.postcheck_rebuilt_table`, `sick.non_sick_rows_unchanged`]:
- All 8,389 SICK rows now equal (relatedness - 1) / 4.
- The STS Companion and STS12 rows are identical to before (same pairs, scores and sources).
- The row count is unchanged: 14,429 rows (STS Companion 5,237, STS12 train 803, SICK-EN 8,389). The STS-B held-out
  leakage rule ran again with the same result.

Measured on the rebuilt table by source, with the T193 word-set Jaccard:

| Source | Rows | Label mean | Std | Word-overlap Spearman |
|---|---|---|---|---|
| SICK-EN | 8,389 | 0.637 | 0.245 | 0.587 (was -0.136) |
| STS Companion | 5,237 | 0.619 | 0.331 | 0.566 |
| STS12 train | 803 | 0.592 | 0.264 | 0.499 |
| All | 14,429 | 0.628 | 0.280 | 0.556 (was 0.014) |

Still open for T197: the extra pairs average 0.628, above STS-B validation (0.473) and train (0.540). The T191 reading
that the similarity head sits at a high training label mean therefore still applies after the fix.

**Licence.** SICK-EN is CC-BY-NC-SA-3.0. Its state is a single one, `APPROVED_BY_OWNER` (owner decision of 2026-11-14,
research use). `license_approved: false` in the sources file only records that the publisher licence is not open; the
acquisition code combines it with `OWNER_APPROVED_DATASETS` into that one manifest status. Any checkpoint trained on
SICK-EN must not be released or used commercially. This is recorded in:
- the SICK-EN notes in `configs/data/english_sources.yaml`;
- `data/acquisition_manifest.json`;
- `docs/specifications/DATASET_SPECIFICATION.md`.

Rows keep `source: SICK-EN`, so filtering them out needs no rebuild.

## 2. QA: `squad/train`

Rule: drop a SQuAD v1 training row when its normalised (question, context) pair occurs in `squad_v2_en` validation or
test (12,733 distinct pairs). The match is on the pair, not on the article.

Effects:
- Only SQuAD v1 train changes.
- The SQuAD 2.0 unanswerable questions are never touched. They live only in the SQuAD 2.0 splits, and those files are
  byte-identical after the run.

Result [`squad`]:
- 87,599 rows before, 9,280 removed, 78,319 after.
- 0 SQuAD v1 training pairs are left in SQuAD 2.0 held-out.
- The QA training pool loses about 3 % of its rows.

Files unchanged, sha256 before equals after [`untouched_files_identical: true`]: `squad/val`, `squad/test`,
`squad_v2_en/train`, `squad_v2_en/val`, `squad_v2_en/test`.

`data/processed/task_splits_manifest.json`, SQUAD train entry: 87,599 -> 78,319 rows and sha256 `1a46e03b…` ->
`36fdb61e…`. All three SQuAD splits verify against the manifest.

Not changed (not in the owner decision): 77,591 `squad_v2_en` training rows still duplicate SQuAD v1 rows, so those
questions are trained twice. This is duplication within training data, not a held-out leak.

## 3. Lineage

- **Originals.** Copied before any write to `data/cache/superseded/T206/` (outside Git): `sts_extra_en/train.parquet`
  sha256 `e8dabecd…` and `squad/{train,val,test}.parquet`. Backups are never overwritten with other content.
- **Frozen T96 revision.** `data/processed/r1/squad` was a symlink to `../squad`. It is now a copy of the original files,
  so the frozen revision keeps its checksums [`r1_squad_frozen`, `r1_squad_verifies: true`].
- **Evidence left as measured.** The T175 leakage report and the T193 audit are not rewritten. Their figures describe the
  data before this correction.
- **Historical artifact not updated.** `configs/data/foundation_sampling.yaml` (the F04A sampling proposal) still names
  the old SQuAD train checksum.

Reproduce:
- Dry run (precheck and counts only): `HOME=$(mktemp -d) .venv/bin/python -I scripts/correct_pair_data.py`
- Apply: add `--apply`.

Tests: `tests/unit/scripts/test_correct_pair_data.py`.
