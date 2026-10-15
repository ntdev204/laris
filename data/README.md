# LARIS Data Directory

This directory is the local storage location for scientific literature, preprocessed corpora, tokenization training data, and evaluation splits.

> [!CAUTION]
> In accordance with repository policies and `.gitignore`, raw scientific papers, large text dumps, and preprocessed dataset partitions MUST NOT be committed to Git.

## Subdirectory Structure
- `data/raw/`: Original ingested files (PDF, HTML, LaTeX, TXT).
- `data/processed/`: Normalized, deduplicated, and partitioned corpus splits (`train/`, `val/`, `test/`).
- `data/cache/`: Local index caches and temporary parsing buffers.
