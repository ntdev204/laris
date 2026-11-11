---
type: playbook
domain: literature-mining
level: 2
summary: Scope the corpus, deduplicate, extract per document, aggregate with stated scope, report trends with their limits.
version: 1.0.0
parent: '[[Literature Mining]]'
uses:
- '[[Inclusion Criteria]]'
- '[[Term Frequency Trends]]'
requires:
- '[[Evidence Sufficiency]]'
---

# Literature Mining Playbook

Scope the corpus, deduplicate, extract per document, aggregate with stated scope, report trends with their limits.


## Decide
- Restate the mining question as a population of documents and a quantity to measure.
- Check corpus_status first: an empty or tiny corpus ends the task with a clear message.
- Prefer counts per document over counts per passage so long papers do not dominate.

## Verify
- Every statistic names its corpus, its time span and its denominator.
- Sample at least three source documents behind each reported trend and cite them.
- Separate what the documents say from what the aggregation suggests.

## Stop
- Stop when the question is answered at the stated scope; do not extrapolate beyond the corpus.
- Stop and report when evidence is fewer than three documents.
