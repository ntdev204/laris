---
document_id: "DOC-SPEC-TOOL-001"
title: "LARIS Tool System Specification"
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
  - "docs/specifications/SKILL_SPECIFICATION.md"
decision_references:
  - "ADR-006"
change_summary: "Specification of executable tools, schema validation, and failure isolation."
---

# LARIS Tool System Specification

## 1. Overview & Tool Definition

A **Tool** in LARIS is a deterministic, executable software component with strict input/output schemas, sandboxed error boundaries, and explicit execution timeouts.

Tools represent the atomic physical actuators through which autonomous agents and skills interact with files, databases, algorithms, and models.

---

## 2. Core Tool Catalog

| Tool ID | Tool Name | Scope & Function | Determinism |
| :--- | :--- | :--- | :--- |
| `TOOL-PDF-LAYOUT-PARSER` | `parse_pdf_layout` | Converts PDF bytes into canonical `DocumentTree` with coordinates. | High |
| `TOOL-CORPUS-SEARCH` | `query_corpus_bm25` | Executes lexical search with STEM token stemming against corpus. | 100% Deterministic |
| `TOOL-GRAPH-TRAVERSAL` | `query_evidence_graph` | Traverses Layer 5 Evidence Graph for k-hop paths and contradictions. | 100% Deterministic |
| `TOOL-UNIT-NORMALIZER` | `normalize_stem_units` | Normalizes electrical/STEM units (GHz, dB, V, W) into SI base units. | 100% Deterministic |
| `TOOL-BENCHMARK-RUNNER` | `execute_benchmark_suite`| Runs automated capability regressions against frozen evaluation sets. | 100% Deterministic |
| `TOOL-COORDINATE-RESOLVER`| `resolve_text_coordinates` | Resolves sentence or token spans to exact page, line, and bounding box. | 100% Deterministic |

---

## 3. Tool Execution Invariants

1. **Strict Type Enforcement:** Tool arguments and return values MUST validate against their JSON schema before and after execution.
2. **Hard Timeouts:** Every tool execution has an enforced wall-clock timeout (default 30 seconds); timeout violations abort execution immediately.
3. **No Unchecked Exceptions:** All internal tool failures must be mapped to typed `ToolExecutionError` classes with structured error payloads.
