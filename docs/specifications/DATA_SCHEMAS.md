---
document_id: "DOC-SPEC-SCHEMA-001"
title: "LARIS Core Data Schemas Specification"
document_type: "specification"
status: "DRAFT"
version: "0.2.0"
created_at: "2026-10-15"
updated_at: "2026-10-29"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/architecture/SYSTEM_OVERVIEW.md"
  - "docs/specifications/MODULE_CONTRACTS.md"
  - "docs/architecture/EVIDENCE_AND_PROVENANCE.md"
decision_references:
  - "ADR-004"
change_summary: "Field tables replace the verbose JSON Schema listings; required fields, enums and ranges are unchanged."
---

# LARIS Core Data Schemas Specification

All data exchanged between modules MUST conform to these schemas. The Python models in `src/laris/` (for example `laris.core`, `laris.reasoning.schemas`) are the executable form; JSON Schema draft 2020-12 is the interchange form. A field marked **required** must be present; ranges are inclusive.

## 1. `EvidenceCoordinate`

| Field | Type | Constraint |
| :--- | :--- | :--- |
| `coordinate_id` | string | required |
| `document_id` | string | required |
| `document_sha256` | string | required, matches `^[a-f0-9]{64}$` |
| `page_number` | integer | required, at least 1 |
| `section_identifier` | string | required |
| `paragraph_index` | integer | required, at least 0 |
| `sentence_index` | integer | required, at least 0 |
| `char_start`, `char_end` | integer | required, at least 0 |
| `verbatim_snippet` | string | required |
| `extraction_confidence` | number | optional, 0.0 to 1.0 |

## 2. `ScientificClaim`

| Field | Type | Constraint |
| :--- | :--- | :--- |
| `claim_id` | string | required |
| `canonical_text` | string | required |
| `epistemic_status` | enum | required: `DIRECT_AUTHOR_CLAIM`, `EMPIRICALLY_SUPPORTED_FINDING`, `MULTI_SOURCE_SYNTHESIS`, `HYPOTHESIS`, `INSUFFICIENT_EVIDENCE`, `CONFLICTING_EVIDENCE`, `UNVERIFIABLE_ASSERTION` |
| `evidence_coordinates` | array of string | required, at least 1 item (`coordinate_id` values) |
| `related_methods`, `measured_metrics` | array of string | optional |
| `confidence_score` | number | required, 0.0 to 1.0 |

## 3. `ResearchGap`

| Field | Type | Constraint |
| :--- | :--- | :--- |
| `gap_id`, `title`, `description` | string | required |
| `gap_class` | enum | required: `KNOWLEDGE_GAP`, `METHODOLOGICAL_GAP`, `MEASUREMENT_EVALUATION_GAP`, `DATASET_DOMAIN_GAP`, `GENERALIZATION_GAP`, `REPRODUCIBILITY_GAP`, `CONFLICTING_EVIDENCE_GAP`, `ASSUMPTION_BOUNDARY_GAP`, `INTEGRATION_INTERDISCIPLINARY_GAP`, `DEPLOYMENT_RESOURCE_GAP`, `TEMPORAL_GAP`, `UNDEREXPLORED_RESEARCH_QUESTION` |
| `epistemic_rationale` | string | required |
| `supporting_evidence` | array of string | required |
| `counter_evidence_searched` | boolean | optional |
| `calibrated_scores` | object | required; `novelty`, `grounding`, `feasibility`, `significance`, `uncertainty`, `composite_score`, each a required number from 0.0 to 1.0 |
| `validation_plan` | object | required; `proposed_methodology` (string), `required_datasets`, `expected_baselines`, `evaluation_metrics` (arrays of string), all required |

## 4. `TelemetrySnapshot`

| Field | Type | Constraint |
| :--- | :--- | :--- |
| `timestamp_iso` | string | required, `date-time` |
| `vram_allocated_bytes`, `vram_reserved_bytes`, `host_ram_used_bytes` | integer | required, at least 0 |
| `active_specialist_id` | string | required |
| `active_param_count` | integer | required, at least 0 |
| `weight_transfer_ms`, `inference_latency_ms` | number | optional, at least 0.0 |
