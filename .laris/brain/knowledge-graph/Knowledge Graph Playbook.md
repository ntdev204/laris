---
type: playbook
domain: knowledge-graph
level: 2
summary: Extract entities and relations, resolve duplicates, type the relations, store provenance, and answer from paths.
version: 1.0.0
parent: '[[Knowledge Graph]]'
uses:
- '[[Entity Resolution]]'
- '[[Relation Typing]]'
- '[[Path Evidence]]'
requires:
- '[[Relation Vocabulary]]'
---

# Knowledge Graph Playbook

Extract entities and relations, resolve duplicates, type the relations, store provenance, and answer from paths.


## Decide
- Extract candidate entities and relations per passage, never per guess.
- Resolve entities before adding edges; keep aliases.
- Use only relation types from the relation vocabulary; propose new types instead of inventing them.

## Verify
- Every edge stores its passage and document; an edge without provenance is discarded.
- A path answer lists each edge with its source.
- Report graph size, edges per type and the share of entities resolved.

## Stop
- Stop extraction when new passages add no new entities or edges.
- Do not answer from a path longer than the configured hop limit.
