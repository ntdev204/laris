# Measured reports

Versioned measurements belong here; specifications and plans belong in `docs/`.
Reports describe a particular run and do not automatically qualify a model.

- `language_encoder/`: checkpoint evaluation outputs. The existing validation report
  passed baseline-relative floors, but did not meet formal foundation exit gates.
- `scientific_nlp/`: the historical 20-paper diagnostic corpus manifest and pilot
  results, including manual extraction failures. This is not model 02 completion.
- `model_free/`: output of `laris-server evaluate suite` (retrieval, citation, extraction, leak,
  injection and vault round-trip on fixtures). Reproducible; says nothing about the core model.
- `performance/`: output of `scripts/benchmark_vault.py` (10,000-note vault) and its budgets.
- `verification/`: preparation-task checks. These record engineering verification,
  never training results or capability promotion.

Keep weights, training state, downloaded PDFs, tokenizer files and data shards in
the ignored `artifacts/` and `data/` directories. Preserve old measured JSON files
unchanged when moving them; put interpretation and corrections in documentation.
