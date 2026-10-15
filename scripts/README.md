# LARIS Automation & Validation Scripts

This directory houses automated developer utilities, documentation validators, benchmark runners, and quality gate scripts.

## Key Scripts
- `validate_docs.py`: Validates documentation metadata, uniqueness of document IDs, allowed lifecycle status enums, internal link resolution, and ADR cross-references.

## Usage
To execute the documentation quality gate:
```bash
python3 scripts/validate_docs.py
```
