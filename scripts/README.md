# LARIS Scripts

Operational entry points live in the `laris` CLI (`laris --help`); the files here are thin
compatibility wrappers plus documentation tooling.

## Tooling
- `validate_docs.py`: validates documentation metadata, uniqueness of document IDs, lifecycle status, internal links and ADR cross-references.
- `verify_target_server.sh`: checks the target server hardware and environment.

## Model block
- `check_chat_backend.py`: one prompt through `/v1/chat/completions` on a running model service (T231).
- `record_scientific_fixtures.py`: records the scientific tool fixtures.
- `verify_model_block.py`: the no-training guard plus lint, types and the test suite.
- `validate_spec.py`: validates the ledger (`.claude/spec`).
- `benchmark_vault.py`: latency of the vault index.
- `stem_benchmarks.py`: STEM benchmark download, seeded dev / sealed splits, 13-gram leakage scan and the bare-model baseline (T275, ADR-026; settings in `configs/stem-benchmarks.json`). Inference only.
- `acquire_openstax.py`, `build_stem_brain.py`: the pinned OpenStax books and the STEM main-brain snapshot build, B6 scan and retrieval recall (T277; settings in `configs/stem-brain.json`).
- `acquire_papers.py`: proposes (OpenAlex) and fetches (Crossref, Europe PMC) the journal papers of T285 with each paper's verdict; `build_stem_brain.py build NAME --sources configs/admissible-sources.json`, `certify NAME` and `brain-only NAME` build and measure a snapshot with admission records. Network only at acquisition.

The dataset acquisition, partition, tokenizer and encoder training scripts were removed in T233 (D48).

## Usage
```bash
python3 scripts/validate_docs.py
```
