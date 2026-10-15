---
document_id: "DOC-SPEC-SKILL-001"
title: "LARIS Skill System Specification"
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
  - "docs/specifications/TOOL_SPECIFICATION.md"
  - "docs/specifications/AGENT_SPECIFICATION.md"
decision_references:
  - "ADR-006"
change_summary: "Definition of the declarative skill model, lifecycles, and interface contracts."
---

# LARIS Skill System Specification

## 1. Overview & Concept

A **Skill** in LARIS represents a modular, high-level scientific capability that can be dynamically loaded and invoked by autonomous agents without requiring architectural modification or full model retraining.

Skills combine domain rules, specialized models, executable tools, and evaluation benchmarks into a declarative package.

---

## 2. Skill Schema & Contract

Every skill is defined by a canonical descriptor:

```yaml
skill_id: "SKILL-EXTRACT-CLAIMS"
name: "extract_scientific_claims"
version: "0.1.0"
description: "Extracts fine-grained scientific claims, empirical findings, and limitations from normalized DocumentTrees."
prerequisites:
  models:
    - "MOD-LANG-001"
    - "MOD-SCINLP-001"
  tools:
    - "TOOL-DISCOURSE-PARSER"
    - "TOOL-COORDINATE-RESOLVER"
inputs:
  document_tree: "DocumentTree"
  confidence_threshold: 0.85
outputs:
  extracted_claims: "List[ScientificClaim]"
  extraction_metadata: "dict"
evaluation_benchmark: "BENCH-CLAIM-EXTRACT-V1"
resource_budget:
  max_vram_mb: 2048
  max_latency_sec: 10
```

---

## 3. Standard Core Skills

LARIS Milestone M0 establishes five baseline skill specifications:
1. `extract_scientific_claims`: Discovers claims, methods, metrics, and experimental outcomes.
2. `compare_experimental_methods`: Constructs cross-paper comparative condition matrices.
3. `infer_latent_limitations`: Identifies unstated boundary conditions and limitations in narrative text.
4. `detect_empirical_contradictions`: Searches for conflicting quantitative results across studies.
5. `evaluate_research_gap`: Evaluates candidate gaps across the 12-class taxonomy and computes calibrated scores.
