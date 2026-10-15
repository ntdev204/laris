---
document_id: "DOC-SPEC-SCHEMA-001"
title: "LARIS Core Data Schemas Specification"
document_type: "specification"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/IDEA.md"
  - "docs/specifications/MODULE_CONTRACTS.md"
  - "docs/architecture/EVIDENCE_AND_PROVENANCE.md"
decision_references:
  - "ADR-004"
change_summary: "Formal JSON and Python schema definitions for core entities: DocumentTree, EvidenceCoordinate, Claim, Gap, Report, Telemetry."
---

# LARIS Core Data Schemas Specification

## 1. Overview

This document specifies the canonical data schemas utilized across LARIS module boundaries. All data exchanged between layers MUST conform strictly to these schemas.

---

## 2. Evidence Coordinate Schema (`EvidenceCoordinate`)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "EvidenceCoordinate",
  "type": "object",
  "required": [
    "coordinate_id", "document_id", "document_sha256", 
    "page_number", "section_identifier", "paragraph_index", 
    "sentence_index", "char_start", "char_end", "verbatim_snippet"
  ],
  "properties": {
    "coordinate_id": { "type": "string" },
    "document_id": { "type": "string" },
    "document_sha256": { "type": "string", "pattern": "^[a-f0-9]{64}$" },
    "page_number": { "type": "integer", "minimum": 1 },
    "section_identifier": { "type": "string" },
    "paragraph_index": { "type": "integer", "minimum": 0 },
    "sentence_index": { "type": "integer", "minimum": 0 },
    "char_start": { "type": "integer", "minimum": 0 },
    "char_end": { "type": "integer", "minimum": 0 },
    "verbatim_snippet": { "type": "string" },
    "extraction_confidence": { "type": "number", "minimum": 0.0, "maximum": 1.0 }
  }
}
```

---

## 3. Scientific Claim Entity Schema (`ScientificClaim`)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ScientificClaim",
  "type": "object",
  "required": [
    "claim_id", "canonical_text", "epistemic_status", 
    "evidence_coordinates", "confidence_score"
  ],
  "properties": {
    "claim_id": { "type": "string" },
    "canonical_text": { "type": "string" },
    "epistemic_status": {
      "type": "string",
      "enum": [
        "DIRECT_AUTHOR_CLAIM",
        "EMPIRICALLY_SUPPORTED_FINDING",
        "MULTI_SOURCE_SYNTHESIS",
        "HYPOTHESIS",
        "INSUFFICIENT_EVIDENCE",
        "CONFLICTING_EVIDENCE",
        "UNVERIFIABLE_ASSERTION"
      ]
    },
    "evidence_coordinates": {
      "type": "array",
      "items": { "type": "string" },
      "minItems": 1
    },
    "related_methods": { "type": "array", "items": { "type": "string" } },
    "measured_metrics": { "type": "array", "items": { "type": "string" } },
    "confidence_score": { "type": "number", "minimum": 0.0, "maximum": 1.0 }
  }
}
```

---

## 4. Research Gap Entity Schema (`ResearchGap`)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ResearchGap",
  "type": "object",
  "required": [
    "gap_id", "gap_class", "title", "description", 
    "epistemic_rationale", "supporting_evidence", 
    "calibrated_scores", "validation_plan"
  ],
  "properties": {
    "gap_id": { "type": "string" },
    "gap_class": {
      "type": "string",
      "enum": [
        "KNOWLEDGE_GAP",
        "METHODOLOGICAL_GAP",
        "MEASUREMENT_EVALUATION_GAP",
        "DATASET_DOMAIN_GAP",
        "GENERALIZATION_GAP",
        "REPRODUCIBILITY_GAP",
        "CONFLICTING_EVIDENCE_GAP",
        "ASSUMPTION_BOUNDARY_GAP",
        "INTEGRATION_INTERDISCIPLINARY_GAP",
        "DEPLOYMENT_RESOURCE_GAP",
        "TEMPORAL_GAP",
        "UNDEREXPLORED_RESEARCH_QUESTION"
      ]
    },
    "title": { "type": "string" },
    "description": { "type": "string" },
    "epistemic_rationale": { "type": "string" },
    "supporting_evidence": { "type": "array", "items": { "type": "string" } },
    "counter_evidence_searched": { "type": "boolean" },
    "calibrated_scores": {
      "type": "object",
      "required": ["novelty", "grounding", "feasibility", "significance", "uncertainty", "composite_score"],
      "properties": {
        "novelty": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
        "grounding": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
        "feasibility": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
        "significance": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
        "uncertainty": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
        "composite_score": { "type": "number", "minimum": 0.0, "maximum": 1.0 }
      }
    },
    "validation_plan": {
      "type": "object",
      "required": ["proposed_methodology", "required_datasets", "expected_baselines", "evaluation_metrics"],
      "properties": {
        "proposed_methodology": { "type": "string" },
        "required_datasets": { "type": "array", "items": { "type": "string" } },
        "expected_baselines": { "type": "array", "items": { "type": "string" } },
        "evaluation_metrics": { "type": "array", "items": { "type": "string" } }
      }
    }
  }
}
```

---

## 5. Hardware Telemetry Snapshot Schema (`TelemetrySnapshot`)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "TelemetrySnapshot",
  "type": "object",
  "required": [
    "timestamp_iso", "vram_allocated_bytes", "vram_reserved_bytes", 
    "host_ram_used_bytes", "active_specialist_id", "active_param_count"
  ],
  "properties": {
    "timestamp_iso": { "type": "string", "format": "date-time" },
    "vram_allocated_bytes": { "type": "integer", "minimum": 0 },
    "vram_reserved_bytes": { "type": "integer", "minimum": 0 },
    "host_ram_used_bytes": { "type": "integer", "minimum": 0 },
    "active_specialist_id": { "type": "string" },
    "active_param_count": { "type": "integer", "minimum": 0 },
    "weight_transfer_ms": { "type": "number", "minimum": 0.0 },
    "inference_latency_ms": { "type": "number", "minimum": 0.0 }
  }
}
```
