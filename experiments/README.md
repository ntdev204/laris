# Bounded experiments

These manually invoked experiments are outside the automated test suite and the
production CLI. Outputs and downloaded material go to ignored `artifacts/` paths.

`scientific_nlp/` preserves the earlier 20-paper diagnostic acquisition/inference
scripts. Its pilot requires the source-evidence gate from PR #312. It demonstrates
integration failures, not scientific-language readiness or verified research gaps.
It must not be used to skip the foundation and scientific-language exit gates.

During the current preparation task, agents must not execute training, tokenizer
fitting or optimizer-bearing profiling. The owner training runbook is under
`docs/training/`; historical pilot scripts are not the next training step.
