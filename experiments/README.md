# Bounded experiments

These manually invoked experiments are outside the automated test suite and the
production CLI. Outputs and downloaded material go to ignored `artifacts/` paths.

`scientific_nlp/` keeps the 20-paper acquisition script of the earlier diagnostic pilot. The pilot
script itself needed the self-trained encoder and was removed in T233 (D48); its measured output
stays in `reports/scientific_nlp/`. It demonstrates integration failures, not scientific-language
readiness or verified research gaps.

Agents must not execute training, tokenizer fitting or optimizer-bearing profiling.
