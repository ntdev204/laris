---
document_id: "DOC-SPEC-DATA-002"
title: "LARIS-GOLD Benchmark Specification & Annotation Protocol"
document_type: "specification"
status: "APPROVED"
version: "1.0.0"
created_at: "2026-10-16"
updated_at: "2026-10-16"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/plans/STAGED_LEARNING_PIPELINE.md"
  - "docs/specifications/DATASET_SPECIFICATION.md"
  - "docs/specifications/DATA_SCHEMAS.md"
decision_references:
  - "ADR-001"
  - "ADR-004"
  - "ADR-008"
change_summary: "Formal specification for project-owned gold-standard benchmark (LARIS-GOLD) covering provenance, schema, double-blind curation, and leak-free evaluation splits."
---

# LARIS-GOLD Benchmark Specification & Annotation Protocol

## 1. Scope & Purpose

In accordance with [ADR-004](file:///home/thientn204/laris/docs/adr/ADR-004-evidence-provenance-first-class.md), [ADR-008](file:///home/thientn204/laris/docs/adr/ADR-008-evaluation-before-capability-claims.md), and Section 6.5 of the master execution mandate:
- **Reality Audit:** As confirmed during initial inspection, **LARIS-GOLD does not yet exist as an acquired dataset**.
- **Prohibition on Fabrication:** Fabricating synthetic labels or mock annotations and presenting them as expert-validated gold labels is strictly prohibited.
- **Objective:** This specification establishes the binding schema, curation protocol, quality criteria, and held-out evaluation splits for constructing the official LARIS-GOLD benchmark during future authorized data curation phases.

---

## 2. Benchmark Typology & Epistemic Capabilities

LARIS-GOLD evaluates end-to-end epistemic reasoning across five core capabilities:

1. **Multi-Hop Scientific Evidence Retrieval:**
   Queries requiring synthesizing findings across 2 to 5 distinct research papers to answer complex scientific research questions.
2. **Scientific Claim Verification & Contradiction Detection:**
   Opposing or nuanced scientific claims evaluated against full-text evidence passages with explicit labels: `SUPPORT`, `CONTRADICT`, or `INSUFFICIENT_EVIDENCE`.
3. **Evidence Coordinate Integrity:**
   Validation that every assertion links directly to an immutable `EvidenceCoordinate` (`corpus_id`, `page_number`, `bounding_box`, `sentence_index`, `sha256_digest`).
4. **12-Class Research Gap Identification:**
   Verification against human-curated genuine research gaps classified under the canonical 12-class LARIS gap taxonomy.
5. **Bilingual Evaluation:**
   Parallel STEM benchmark cases in both English ($80\%$) and Vietnamese ($20\%$) to track language capabilities independently.

---

## 3. Schema & Data Structure

Every LARIS-GOLD benchmark instance conforms to the following JSON schema:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "LARISGoldBenchmarkItem",
  "type": "object",
  "required": [
    "case_id",
    "domain",
    "language",
    "query",
    "epistemic_task",
    "gold_verdict",
    "evidence_items",
    "provenance",
    "split"
  ],
  "properties": {
    "case_id": { "type": "string", "pattern": "^LG-[A-Z0-9]{4,8}$" },
    "domain": { "type": "string", "enum": ["Computer Science", "Physics", "Biology", "Medicine", "Mathematics"] },
    "language": { "type": "string", "enum": ["en", "vi"] },
    "query": { "type": "string" },
    "epistemic_task": {
      "type": "string",
      "enum": ["claim_verification", "multi_hop_qa", "gap_identification", "contradiction_detection"]
    },
    "gold_verdict": {
      "type": "string",
      "enum": ["SUPPORTED", "REFUTED", "UNRESOLVED_CONFLICT", "INSUFFICIENT_EVIDENCE"]
    },
    "evidence_items": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["evidence_id", "corpus_id", "source_text", "coordinates"],
        "properties": {
          "evidence_id": { "type": "string" },
          "corpus_id": { "type": "string" },
          "source_text": { "type": "string" },
          "coordinates": {
            "type": "object",
            "required": ["page_number", "sentence_index", "content_hash"],
            "properties": {
              "page_number": { "type": "integer" },
              "sentence_index": { "type": "integer" },
              "bounding_box": { "type": "array", "items": { "type": "number" } },
              "content_hash": { "type": "string", "pattern": "^[a-f0-9]{64}$" }
            }
          }
        }
      }
    },
    "provenance": {
      "type": "object",
      "required": ["curator_role", "verified_by", "inter_annotator_agreement", "timestamp"],
      "properties": {
        "curator_role": { "type": "string" },
        "verified_by": { "type": "string" },
        "inter_annotator_agreement": { "type": "number" },
        "timestamp": { "type": "string" }
      }
    },
    "split": { "type": "string", "enum": ["TRAIN", "VAL", "TEST"] }
  }
}
```

---

## 4. Annotation & Verification Protocol

To ensure unimpeachable quality, all LARIS-GOLD instances must undergo a 3-step verification process:
1. **Double-Blind Primary Annotation:**
   Two domain-expert annotators independently extract claims, evidence spans, and verdicts from candidate papers.
2. **Disagreement Adjudication:**
   Cases with inter-annotator Cohen's $\kappa < 0.85$ are reviewed by a third senior researcher. Unresolvable ambiguities are categorized as `UNRESOLVED_CONFLICT` or discarded.
3. **Source Verification & Coordinate Integrity:**
   Automated verification checks that every quoted evidence span matches character-for-character with the raw PDF/text source and hashes identically to the source text hash.

---

## 5. Held-Out Split Governance

- **Group Isolation:** Partitions are assigned strictly at the research-topic and paper-cluster level. Papers citing each other or sharing authors must remain within the same partition.
- **Test Set Isolation:** The test split ($20\%$ of cases) is cryptographically sealed (`FROZEN`) and must never be exposed during prompt tuning, hard-negative mining, or model evaluation until formal milestone exit audits.
