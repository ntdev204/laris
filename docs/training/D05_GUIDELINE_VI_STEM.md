---
document_id: DOC-PLAN-D05-GUIDELINE-VI-STEM-001
title: Guideline for Vietnamese STEM retrieval relevance (D05-a, version 1.0)
document_type: plan
status: FROZEN
version: 1.0.0
created_at: '2026-11-13'
updated_at: '2026-11-13'
owner: LARIS Project Owner
reviewers: []
source_of_truth: true
related_documents:
- docs/training/D05_HUMAN_GOLD_PROTOCOL.md
decision_references:
- ADR-008
change_summary: Freezes the relevance guideline used by the T98 annotators; its SHA-256 is bound into the sealed gold.
---

# Guideline for Vietnamese STEM retrieval relevance (frozen 2026-11-13)

**Provenance of the labels.** On 2026-11-13 the owner delegated the labelling to the assistant. Every label under this
guideline is produced by a language model (query author, annotators A1 and A2, adjudicator are separate model
invocations that do not see each other's output). The labels are **LLM-assigned relevance, not human gold**; any report
that uses them says so, and the owner accepts that when promoting G12 for Vietnamese.

## 1. Task
Each item has a Vietnamese **query** and a Vietnamese **passage** (a machine-translated biomedical abstract). Judge only
that passage against that query. Do not search for other documents and do not use knowledge outside the passage to decide
what it says.

## 2. Labels
| Label | Meaning | Sign |
|---|---|---|
| 2 | Answers the query | the passage contains enough information to answer the query without another source |
| 1 | Partial | the passage is on topic and supplies part of the answer, or needs another source to be complete |
| 0 | Not relevant | another topic, or only a keyword overlap that does not help answer |

## 3. Boundary rules
1. Same term, different meaning (abbreviation, other field): 0.
2. The passage states the question but not the answer: 1 if it gives context directly needed for the answer, else 0.
3. The answer is present in different wording (paraphrase): 2; do not judge by word overlap.
4. The passage contradicts the answer the query aims at but discusses exactly that question: 2.
5. Numbers or units that differ from the query: 1 if convertible, 0 if not.
6. Machine-translation errors: judge the meaning a careful reader can recover; if the key fact is unrecoverable, use 1 at most.
7. Unsure between two labels: choose the lower one. Never leave an item unlabelled.
8. Ignore the order of items and do not guess which system retrieved a passage.
9. Do not consult other annotators' labels.

## 4. Sheets and adjudication
Each annotator receives blind JSONL sheets (`item_id`, `query`, `passage`, `label`), fills `label` with 0, 1 or 2 for every
row, changes nothing else. A set of sheets with a missing, duplicate or invalid label is rejected. Items on which A1 and A2
differ go to the adjudicator, who sees query, passage and both labels; an unresolved item is excluded and the rate
reported. A batch whose quadratic-weighted kappa is below 0.85 is returned for guideline revision, never adjudicated into
acceptance.
