---
type: concept
domain: citation-analysis
level: 3
summary: Split the reference section, parse each entry into fields, and mark entries that failed.
version: 1.0.0
parent: '[[Citation Extraction]]'
---

# Reference Parsing

Split the reference section, parse each entry into fields, and mark entries that failed.


Locate the reference section by heading. Split entries by numbering or hanging layout. Extract year, first author and title; keep the raw string. Match to a corpus document only on DOI, or on title plus year plus first author. Unmatched references stay in the graph as external nodes.
