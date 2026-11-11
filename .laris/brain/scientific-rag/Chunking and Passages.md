---
type: concept
domain: scientific-rag
level: 3
summary: Passages should be self-contained spans with their source and position, so a citation can be checked.
version: 1.0.0
parent: '[[Retrieval Strategy]]'
---

# Chunking and Passages

Passages should be self-contained spans with their source and position, so a citation can be checked.


Chunk by words with a small overlap; keep the document title and position with every passage. Very short chunks lose context; very long chunks hide the answer. Page-level citation needs the page recorded at ingestion.
