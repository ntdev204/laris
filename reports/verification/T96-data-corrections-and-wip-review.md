# T96 — Data corrections and corpus review

Date: 2026-11-13 · Lineage with checksums: `reports/verification/T96-data-corrections.json` · Script:
`scripts/correct_datasets.py` · No model was loaded, nothing was trained, the test split content was not used for tuning.

## 1. Corrected dataset revision r1 (`data/processed/r1/`, outside Git)

The originals under `data/processed/` are untouched and still match the frozen manifest (re-verified by SHA-256).
`data/processed/r1/` holds the two new versions, symlinks to the 12 unchanged datasets and its own
`task_splits_manifest.json`; use `--data-dir data/processed/r1` to train or evaluate on r1.

| Dataset | Problem found by the F04 audit | Rule (fixed before any scoring) | Result |
|---|---|---|---|
| STS-B | normalized pair overlaps train-val 2, train-test 5, val-test 3 | drop a pair from the earlier split when it occurs in a later one; test never changes | train 5734 → 5725 (-9), val 1500 → 1497 (-3), test 1379 unchanged; overlaps now 0 / 0 / 0 |
| ViQuAD v2 | 5 val and 4 test rows with an `answer_start` one character too early | move the offset to the unique occurrence of the text within 2 characters, else drop the answer | 9 offsets moved (val 5, test 4), 0 answers dropped; no text, question or row count changes; invalid offsets 0; context overlap 0 |

Verification: `laris data check --verify-sha256` passes on both `data/processed` and `data/processed/r1`
(isolated HOME); pair and context overlap and offsets were re-computed independently on r1. Consequence for the ledger:
earlier STS-B and ViQuAD validation numbers (F04, F06) were measured on the original revision and are not comparable
with r1 numbers; the next held-out run must name the revision in its dataset manifest.

## 2. Review of `wip/corpus-acquisition-changes` (`b9a629f`), proposal for the owner

The commit is based on the v1 tree; only its four files matter and all four exist on `laris-v2`. Nothing was merged.

| File | Change | Proposal |
|---|---|---|
| `src/laris/research/corpus/acquisition/sources/s2orc.py` | treat HTTP 400 like 403 (expired signed URL) and refresh the release | **Integrate**: one line, no behaviour risk, needed by the streamed S2ORC run |
| `data/acquisition_manifest.json` | S2ORC entry now describes stage 02 (19,724 papers, 211 MB, `shard-0655.parquet`, checksum) | **Integrate after one fix**: `acquisition_status` is still `SKIPPED_TEMPORARILY` although papers were acquired; set it to the acquired status the schema uses. `schema_valid: false` should be re-checked. Totals (bytes 12,271,859,671) already match the entry |
| `tests/unit/corpus/test_dataset_acquisition.py` | S2ORC check accepts either "skipped and explained" or "streamed, sizes equal to listed files" | **Integrate** together with the manifest change |
| `tests/unit/corpus/test_task_splits.py` | expected tracked datasets 17 → 18 | **Integrate** together with the manifest change |

The S2ORC data is a pretraining/stage-2 resource (identifier-based STEM approximation, open licenses only); it is not
used by any stage-1 gate. Local-only leftovers in `data/raw/s2orc_stage02/` (`shard-0520.parquet.tmp`, `state.json`) are
not part of the manifest and should stay out of Git.
