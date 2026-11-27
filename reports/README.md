# Measured reports

Versioned measurements belong here; specifications and plans belong in `docs/`.
Reports describe a particular run and do not automatically qualify a model.

- `benchmarks/`: STEM benchmark runs of ADR-026 (T275 bare-model baseline on the development splits): scores, Wilson
  intervals and cost only, never benchmark text; a baseline is not a qualification.
- `model_free/`: output of the model-free runner (retrieval, citation, extraction, leak,
  injection and vault round-trip on fixtures). Reproducible; says nothing about the core model.
- `performance/`: output of `scripts/benchmark_vault.py` (10,000-note vault) and its budgets; `rust_bench.json` and
  `rust_budgets.json` are the figures and budgets of `cargo xtask bench` (server, redactor, evidence gate, retrieval).
- `research-gap/`: measured runs of the research-gap workflow (T272) and their reports; the run folders and
  screenshots stay in `artifacts/gap-eval/`.
- `security/`: `report.json` of `cargo xtask security`, one verdict per threat-model test id.
- `verification/`: the open-LLM selection report (T228). Reports of the dropped self-trained model were removed (D48); they remain in git history.

Keep weights, downloaded PDFs and data shards in the ignored `artifacts/` and `data/` directories. Preserve old measured JSON files
unchanged when moving them; put interpretation and corrections in documentation.
