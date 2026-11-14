# LARIS Data Directory

This directory is the local storage location for scientific literature, preprocessed corpora, tokenization training data, and evaluation splits.

> [!CAUTION]
> In accordance with repository policies and `.gitignore`, raw scientific papers, large text dumps, and preprocessed dataset partitions MUST NOT be committed to Git.

## Subdirectory Structure
- `data/raw/`: Original ingested files (PDF, HTML, LaTeX, TXT).
- `data/processed/`: Normalized, deduplicated, and partitioned corpus splits (`train/`, `val/`, `test/`).
- `data/acquisition_manifest.json`: provenance, licence status, sizes and SHA-256 of every acquired source (English stage-1 sources are listed in `configs/data/english_sources.yaml`).
- `data/cache/`: Local index caches and temporary parsing buffers.

## Stage-1 data (English since D46 / ADR-022)
The stage-1 encoder is English only. Vietnamese data under `data/raw` and `data/processed` (`wikipedia_vi`, `cc100_vi_clean`, `vinli`,
`viquad_v2`, `vists`, `gold_vi_stem`, `vi_pubmed_candidate`) is kept outside Git as unused history. English replacement sources are listed in
`configs/data/english_sources.yaml` and recorded in `acquisition_manifest.json`; see `docs/specifications/DATASET_SPECIFICATION.md` section 2.1.
