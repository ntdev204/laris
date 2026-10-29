---
document_id: "DOC-TEST-STRAT-001"
title: "LARIS Test Strategy & Verification Architecture"
document_type: "test"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/archive/IDEA.md"
  - "docs/testing/BENCHMARK_PROTOCOL.md"
  - "docs/testing/ACCEPTANCE_CRITERIA.md"
decision_references:
  - "ADR-007"
  - "ADR-008"
change_summary: "Comprehensive test strategy covering unit, contract, integration, regression, and documentation tests."
---

# LARIS Test Strategy & Verification Architecture

## 1. Testing Pyramid in LARIS

To guarantee that software contracts, epistemic invariants, and physical hardware constraints are satisfied, LARIS implements a five-tier testing pyramid:

```mermaid
flowchart TD
    T5["5. Documentation & Governance Integrity Tests (scripts/validate_docs.py)"]
    T4["4. Hardware Telemetry & Stress Tests (VRAM < 15.0 GB)"]
    T3["3. Scientific Capability Benchmarks (NLI, Gap Discovery, Zero-Hallucination)"]
    T2["2. Integration & Contract Tests (Module I/O Schemas, DAG Workflows)"]
    T1["1. Deterministic Unit Tests (Tokenizers, Unit Normalizers, Graph Logic)"]
    
    T1 --> T2 --> T3 --> T4 --> T5
```

---

## 2. Test Categories & Scopes

1. **Deterministic Unit Tests (`tests/unit/`):** Fast, isolated tests verifying algorithmic components (e.g. SI unit normalizers, Unicode sanitizers, graph path traversal, schema validation). Zero GPU required.
2. **Module Contract Tests (`tests/contract/`):** Verifies that all 11 boundaries conform strictly to input/output JSON schemas defined in `docs/specifications/DATA_SCHEMAS.md`.
3. **Integration & Workflow Tests (`tests/integration/`):** End-to-end multi-agent execution DAGs, verifying that data propagates through ingestion, retrieval, synthesis, and report generation.
4. **Documentation & Governance Tests (`tests/documentation/` & `scripts/validate_docs.py`):** Automated static analysis verifying YAML metadata, unique document IDs, internal link resolution, ADR references, and immutability of frozen baselines.
5. **Hardware Telemetry & Resource Safety Tests:** Stress tests verifying that GPU VRAM usage remains strictly $\le 15.0$ GB on the RTX 5070 Ti and that weight offloading prevents CUDA OOM crashes.
