---
type: concept
domain: knowledge-graph
level: 3
summary: Every edge stores document, passage and extraction method so it can be audited or removed.
version: 1.0.0
parent: '[[Graph Reasoning]]'
---

# Provenance of Edges

Every edge stores document, passage and extraction method so it can be audited or removed.


Store source document, passage id and a confidence label from the extractor, not from the model. When a source is removed, remove or flag its edges. Never present an edge without its provenance.
