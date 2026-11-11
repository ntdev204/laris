---
type: concept
domain: literature-mining
level: 3
summary: Collapse versions of the same work (preprint and journal, repeated uploads) before counting.
version: 1.0.0
parent: '[[Corpus Scoping]]'
---

# Deduplication

Collapse versions of the same work (preprint and journal, repeated uploads) before counting.


Compare titles after normalising case and punctuation, then compare first-author and year, then passage overlap. Keep one representative per work and note the merged ids. Never merge on title alone when titles are short.
