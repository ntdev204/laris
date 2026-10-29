# LARIS Scripts

Operational entry points live in the `laris` CLI (`laris --help`); the files here are thin
compatibility wrappers plus documentation tooling.

## Tooling
- `validate_docs.py`: validates documentation metadata, uniqueness of document IDs, lifecycle status, internal links and ADR cross-references.
- `verify_target_server.sh`: checks the target server hardware and environment.

## Compatibility wrappers (delegate to the CLI)
| Script | CLI command |
|---|---|
| `acquire_datasets.py` | `laris data acquire` |
| `partition_datasets.py` | `laris data partition` |
| `train_tokenizer.py` | `laris train tokenizer` |
| `train_language_encoder.py` | `laris train language-encoder` |

## Usage
```bash
python3 scripts/validate_docs.py
```
