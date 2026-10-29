---
document_id: "DOC-ARCH-LAYER-001"
title: "LARIS Twelve-Layer Architectural Specification"
document_type: "architecture"
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
decision_references:
  - "ADR-001"
  - "ADR-002"
  - "ADR-003"
  - "ADR-004"
  - "ADR-005"
  - "ADR-006"
  - "ADR-011"
  - "ADR-012"
change_summary: "Condensed to one table per layer: responsibility, inputs, outputs and invariants; mapping to domain packages unchanged."
---

# LARIS Twelve-Layer Architectural Specification

The conceptual layers below define responsibilities, interfaces and invariants. They are not a package hierarchy: the physical layout is in the mapping table at the end ([ADR-011](../adr/ADR-011-domain-based-package-refactoring.md), [ADR-012](../adr/ADR-012-elimination-of-parallel-layer-hierarchies.md)).

## 1. Layers

| Layer | Responsibility and key components | Inputs | Outputs | Invariant |
| :--- | :--- | :--- | :--- | :--- |
| **0 Data Governance & Corpus** | Ingestion of permitted text, license and provenance audit, Unicode and math normalization, deduplication, leakage-proof Train/Val/Test partitioning across document and author boundaries. | Raw papers (PDF, HTML, LaTeX, TXT) and public datasets. | Versioned, partitioned corpora with cryptographic provenance manifests. | No unverified or proprietary data enters training; test sets stay unvisited during training. |
| **1 Language Foundation** | In-house tokenizer (BPE or Unigram), morphological and syntax analysis, compact sentence and paragraph encoders. | Clean text from Layer 0. | Token IDs, dependency trees, dense embeddings. | 100% self-built weights; no mandatory external pretrained checkpoint. |
| **2 Semantic Intelligence** | Paraphrase and equivalence classification, 3-way NLI (entailment, contradiction, neutral), scientific coreference, discourse connectives, uncertainty and ambiguity scoring. | Sentence pairs, syntax trees and discourse spans from Layer 1. | NLI probabilities, coreference clusters, discourse DAGs. | High similarity is never assumed to imply entailment without NLI verification. |
| **3 Scientific Language Intelligence** | Discourse unit extraction (claims, methods, datasets, metrics, results), heading-agnostic limitation inference, assumption detection, STEM unit and terminology normalization, epistemic status classification (empirical, correlational, causal, speculative). | Ingested documents and Layer 2 representations. | Structured `Claim`, `Method`, `Result`, `Limitation`, `Assumption` entities. | A missing "Limitations" heading must not prevent limitation inference. |
| **4 Document Intelligence** | Multi-format ingestion (PDF, DOCX, HTML, TXT, LaTeX), reading-order and layout parsing, table and equation extraction, coordinate mapping, extraction-confidence scoring. | Raw document files. | Canonical `DocumentTree` with coordinates and confidence. | Every extracted sentence retains its physical source coordinates. |
| **5 Research Knowledge & Evidence Graph** | Versioned graph of documents, authors, methods, datasets, metrics, claims and evidence; typed edges (`supports`, `contradicts`, `extends`, `reproduces`, `depends_on`, `compares_with`); provenance registry; temporal tracking. | Entities and discourse relations from Layers 3 and 4. | Graph queries, neighborhood subgraphs, contradiction paths. | Inferred edges never overwrite or blur author-asserted edges. |
| **6 Hybrid Hierarchical RAG** | BM25 lexical index, dense retriever on Layer 1 encoders, graph traversal over Layer 5, multi-stage reranker, depth-adaptive controller (sentence, paragraph, section, paper). | User intent and sub-questions. | Ranked, calibrated evidence packages with provenance coordinates. | Retrieval is depth-bounded to prevent context explosion. |
| **7 Research Reasoning Engine** | Cross-paper synthesis, contradiction detection, gap discovery against the 12-class taxonomy, adversarial counter-evidence search, calibrated gap scoring (novelty, grounding, feasibility, significance, uncertainty), hypothesis and validation-plan generation. | Evidence packages (Layer 6) and subgraphs (Layer 5). | Verified research gaps, comparison matrices, validation plans. | Global novelty is never claimed when literature coverage is bounded. |
| **8 Agent Orchestration** | Supervisor, query planner, specialist agents, critical reviewer and report composer running dynamic DAGs under timeouts and review gates ([ORCHESTRATION_SPECIFICATION](../specifications/ORCHESTRATION_SPECIFICATION.md)). | Task objectives and resource budgets. | Task outputs, execution logs, validated synthesis. | Agents act only through typed contracts; hard recursion ceilings forbid infinite loops. |
| **9 Adaptive Model Execution** | Task router (heuristic, small model, reasoning module), weight staging between VRAM, host RAM and NVMe, hardware telemetry, adaptive depth governor. | Execution DAG and live telemetry. | Managed model execution without OOM crashes. | Active VRAM stays at or below 15.0 GB on the RTX 5070 Ti. |
| **10 Evaluation, Feedback & Policy Learning** | Continuous benchmark runner over the eight capability dimensions, scientific error taxonomy, hard-negative mining, contextual-bandit policy optimizer gated by deterministic rewards. | Execution traces, expert feedback, benchmark datasets. | Evaluation reports, routing policies, curated training sets. | Rewards based solely on surface fluency are prohibited. |
| **11 Reporting & User Interface** | Evidence-first structured reports by default, manuscript drafting only on explicit request, interactive evidence viewer, human-in-the-loop feedback console, project and corpus manager. | Findings from Layer 7 and the orchestrated report from Layer 8. | Reports, visualizations, feedback signals to Layer 10. | Every displayed conclusion links to its verified evidence coordinates. |

## 2. Conceptual Layers vs Canonical Domain Packages

All parallel numbered layer directories (`src/laris/layers/layerX_*`) are retired. Each layer maps to one authoritative domain package:

| Conceptual Layer | Cognitive Role | Physical Domain Package | Primary Module Exports |
| :--- | :--- | :--- | :--- |
| **Layer 0** | Corpus & Data Governance | `laris.corpus` | `Layer0Pipeline`, `normalize_scientific_text`, `DeduplicationEngine`, `DatasetPartitionEngine` |
| **Layer 1** | Language Foundation | `laris.language` | `STEMSubwordTokenizer`, `CompactSentenceEncoder`, `LexicalBM25Baseline` |
| **Layer 2** | Semantic Relations & Calibration | `laris.reasoning` | `ScientificNLIEngine`, `ConfidenceCalibrator`, `SemanticRelationClassifier` |
| **Layer 3** | Scientific NLP & Discourse | `laris.scientific` | `DiscourseExtractor`, `LimitationExtractor`, `STEMUnitNormalizer` |
| **Layer 4 / 5** | Heterogeneous Evidence Graph | `laris.graph` | `SQLiteEvidenceGraphAdapter`, `EvidenceNode`, `EvidenceEdge` |
| **Layer 6** | Hybrid Hierarchical Retrieval | `laris.retrieval` | `HybridRetrievalEngine`, `ReciprocalRankFusion`, `DenseRetrievalAdapter` |
| **Layer 7** | Research Gap Discovery Engine | `laris.reasoning` | `MatrixSynthesisEngine`, `GapClassifier`, `ConflictDetector`, `AdversarialEngine` |
| **Layer 8** | Multi-Agent Orchestration | `laris.orchestration`| `OrchestrationRuntime`, `SpecialistSupervisor`, `TokenBudgetGovernor` |
| **Layer 9** | Adaptive Local Execution | `laris.execution` | `TaskRouter`, `HardwareTelemetryMonitor`, `HeadroomGovernor`, `WeightStaging` |
| **Layer 10** | Feedback & Policy Learning | `laris.evaluation` | `BenchmarkRunner`, `ScientificErrorTaxonomy`, `FeedbackMiner` |
| **Layer 11** | Epistemic Reporting & Packaging | `laris.reporting` | `StructuredReportGenerator`, `EvidenceInspector`, `ManuscriptComposer` |
| **Shared** | Universal Schemas & Errors | `laris.core` | `EvidenceCoordinate`, `LarisError`, `ModuleContractViolationError` |

