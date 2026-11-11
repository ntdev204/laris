---
type: playbook
domain: citation-analysis
level: 2
summary: Parse references, link them to documents, compute structure at a stated scope, and report metric limits.
version: 1.0.0
parent: '[[Citation Analysis]]'
uses:
- '[[Reference Parsing]]'
- '[[Impact Metrics Caveats]]'
feeds:
- '[[Knowledge Graph Playbook]]'
---

# Citation Analysis Playbook

Parse references, link them to documents, compute structure at a stated scope, and report metric limits.


## Decide
- Decide whether the question is about references (what a paper cites) or about citations (who cites a paper).
- Parse reference strings into author, year, title, venue; match to corpus documents only on strong keys.
- Choose metrics that fit the question and the size of the graph.

## Verify
- Report coverage: the share of references that were parsed and matched.
- Citation counts are relative to the corpus; never present them as global impact.
- Read the citing sentence before calling a citation supportive or critical.

## Stop
- Stop when parsing coverage is too low for the metric to mean anything; report the coverage instead.
- Do not rank people or institutions from a small corpus.
