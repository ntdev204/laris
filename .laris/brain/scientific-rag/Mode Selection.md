---
type: concept
domain: scientific-rag
level: 3
summary: bm25 for exact terms and names, dense for paraphrase, hybrid when unsure or the corpus is mixed.
version: 1.0.0
parent: '[[Retrieval Strategy]]'
---

# Mode Selection

bm25 for exact terms and names, dense for paraphrase, hybrid when unsure or the corpus is mixed.


Rare identifiers, formulas and names are matched best by lexical search. Conceptual questions phrased differently from the source are matched best by dense search. Hybrid fuses both rankings and is the safe default when a model for embeddings is available. If a mode is unavailable, use bm25 and say so.
