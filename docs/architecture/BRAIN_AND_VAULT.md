---
document_id: "DOC-ARCH-BRAIN-VAULT-001"
title: "Architecture of the Project Vault, the System Brain and the Scholarly Analytics"
document_type: "architecture"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-11-11"
updated_at: "2026-11-11"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/specifications/OBSIDIAN_VAULT_FORMAT.md"
  - "docs/architecture/BRAIN_THREAT_MODEL.md"
  - "docs/architecture/AGENT_HARNESS.md"
  - "docs/development/OWNER_RUNBOOK.md"
decision_references:
  - "ADR-014"
  - "ADR-016"
  - "ADR-017"
change_summary: "Describes how the project vault, the protected brain, retrieval and the scholarly analytics fit together, with the measured figures."
---

# Architecture of the Project Vault, the System Brain and the Scholarly Analytics

## 1. Two stores with different owners

| | Project vault (`vault/`) | System brain (`.laris/brain/`) |
|---|---|---|
| Owner | the user, in the user's codebase | the system owner, on the server |
| Writable at runtime | yes, only inside managed blocks | never |
| Format | Obsidian Markdown (`docs/specifications/OBSIDIAN_VAULT_FORMAT.md`) | the same format, a hub tree |
| Reaches the model as | search results marked untrusted | short briefs marked internal |
| Reaches the user as | files they open and edit | note titles only |

The vault is memory of the project; the brain is guidance for reasoning. Learnings never move from the vault
into the brain: they wait in `_inbox/` for review and, once accepted, enter the *vault* (`vault/proposals.py`).

## 2. Modules

```
vault/notes.py       parse a note (properties, links, tags, block ids); size, depth and alias caps
vault/index.py       link resolution, backlinks, orphans; deterministic dump; disposable cache
vault/writer.py      atomic write, confinement, managed blocks, backups, rate limit, redaction
vault/schema.py      note types from .laris/vault/schema.yaml (under the integrity lock)
vault/lint.py        format, hierarchy, content (secrets, oversize, aliases) problems with codes
vault/graph.py       degree, PageRank, components, paths, local graphs
vault/search.py      BM25 over notes
vault/retrieval.py   link-aware retrieval, fusion with corpus search, navigation-first over the brain
vault/project.py     the project vault: Sources, Concepts, Claims, Questions, Sessions, Memory, Analyses
vault/entities.py    method, dataset, metric, claim, limitation notes with character spans
vault/memory.py      memory in the vault and its migration from .laris/memory
vault/proposals.py   the inbox: propose, review, accept, reject
vault/repair.py      sync (hand edits), repair, restore from backup
vault/brain.py       the protected hub tree: route, open, neighbours, consult (budgeted)
scholarly/biblio.py     title, authors, year, DOI, arXiv from text and PDF metadata
scholarly/mining.py     overview, term trends, near-duplicates, groups
scholarly/citations.py  reference lists, in-text citations, resolution, citation graph
scholarly/kg.py         knowledge graph with provenance; JSON, GraphML, Obsidian canvas
agent/scholarly_tools.py  the tools that expose the above to the agent
evaluation/suite.py     the model-free evaluation suites
```

## 3. What one document becomes

Ingest (`vault/hooks.py: record_ingest`) turns each new document into:

1. a **Source** note with `doc_id`, the SHA-256 of the cleaned text, character and passage counts and, when
   the text states them, `bib_title`, `authors`, `year`, `doi`, `arxiv` (never guessed);
2. **Concept** notes for key terms, and **method / dataset / metric** notes (`Concepts/`) and **claim /
   limitation** notes (`Claims/`) whose `char_start` and `char_end` locate the quoted text in the document;
   the same entity found in two documents is one note with two mentions (stable id);
3. a **Knowledge** note under the matching domain hub, which the brain lists next to that hub.

A finished, verified chat turn adds a **Question** note linking the sources it cited, the project notes the
brain pointed to (`notes_used`, only notes that exist) and the brain path as titles. Any failure writes
nothing and never fails the turn.

## 4. Retrieval

`search_vault` ranks notes with BM25, then adds the neighbours of the best hits with a decayed score, so a
note that explains a hit is found even when it shares no words with the query. Each result says whether it
came from the words (`bm25`) or from a link (`link`, with the seed). On the retrieval fixture, BM25 alone
reaches Recall@5 0.583 and graph retrieval 1.0 (`reports/model_free/report.json`). The inbox is excluded.
The brain is navigated first (root, hub, playbook, typed links) and searched only when no hub matches.

## 5. Scholarly analytics

The tools `corpus_overview`, `term_trends`, `find_duplicates`, `group_documents`, `save_analysis`,
`citation_graph` and `kg_query` and the workflows `literature-map`, `citation-analysis` and `kg-explore` work
on the user's corpus. Rules that keep them honest: every result names its scope (documents, documents with
a year, documents left out); a reference becomes a citation edge only on a DOI, arXiv or whole-title match,
and weak or ambiguous matches are listed, not used; every knowledge-graph edge carries its provenance (note,
character span or reference line).

## 6. Where each part runs

With the policy server (ADR-016) the brain, the prompt and the policy stay on the server; the client keeps
the vault, the corpus and the tools above. The server never sees the vault. `kg_query`, `search_vault`
and the analytics are client tools, so their results reach the server only as tool results of the user's own
turn.

## 7. Measured figures

Vault of 10,000 notes (`scripts/benchmark_vault.py`, development workstation): full index 2.6 s, one-note
update 0.52 s, peak memory 182 MB, BM25 search P95 18 ms. Budgets are in `reports/performance/budgets.json`;
a figure more than 20 percent over its budget fails `make bench-vault`.

## 8. Limits

- The extractor is rule-based and English-oriented: on the fixture, micro precision 1.00 and recall 0.88.
- Bibliographic fields stay empty when the first page does not state them.
- The shingle leak guard sees words, not meaning (residual risk in `BRAIN_THREAT_MODEL.md`).
- None of this says anything about the core model, which is NOT QUALIFIED.
