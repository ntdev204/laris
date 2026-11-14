# T175: English stage-1 data acquisition (2026-11-14)

The foundation model is **NOT QUALIFIED**. This report records data on disk, not capability.

- Order: the owner asked for at least 20 GB of English data for stage 1 covering all semantic cases (2026-11-14), after D46 / ADR-022.
- Result: 32 sources from `configs/data/english_sources.yaml`, **33.0 GB and 21.2 million records** of English stage-1 data in total (local English corpora included), all with SHA-256 in `data/acquisition_manifest.json`. Per-source table: `docs/specifications/DATASET_SPECIFICATION.md` section 2.1.
- Roles: MLM text 22.7 GB (about 11.8 B tokens by characters/4.2, an estimate), retrieval pairs 3.2 GB, QA 2.3 GB, paraphrase 0.5 GB, NLI and similarity small.
- Licences: 15 sources are `NEEDS_LICENSE_REVIEW` (research-only until the owner approves). Acquisition was ordered by the owner; that is not a licence clearance.
- Leakage: `scripts/check_sts_leakage.py` removed 2,092 extra similarity pairs that share a sentence with STS-B validation or test, and 842 duplicates; 14,429 pairs remain (`reports/verification/T175-sts-leakage.json`).
- Not done: the new sources are not partitioned (T177), there is no English tokenizer or mixture config, and no training or fitting was run by the agent.
- Prepared, not downloaded (owner decision pending on the S2ORC fields filter): `configs/data/science_sources.yaml` (stage 2, 13 GB), `configs/data/ocr_sources.yaml` (stage 3 PDFs), `configs/data/s2orc_fields.yaml`.
