# LARIS Data Directory

This directory is the local storage location for scientific literature and corpora.

> [!CAUTION]
> In accordance with repository policies and `.gitignore`, raw scientific papers, large text dumps, and preprocessed dataset partitions MUST NOT be committed to Git.

## Subdirectory Structure
- `data/raw/`: Original ingested files (PDF, HTML, LaTeX, TXT).
- `data/processed/`: Normalized, deduplicated, and partitioned corpus splits.
- `data/acquisition_manifest.json`: provenance, licence status, sizes and SHA-256 of every source acquired for the self-trained model; kept as a record.
- `data/cache/`: Local index caches and temporary parsing buffers.

## Self-trained model data
The acquisition, partition and leakage tooling for the self-trained encoder was removed in T233 (D48); nothing here is read by the running system.
