---
document_id: "DOC-ARCH-LAYER-001"
title: "LARIS Twelve-Layer Architectural Specification"
document_type: "architecture"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/architecture/SYSTEM_OVERVIEW.md"
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
change_summary: "Detailed structural specification of all 12 architectural layers and mapping to canonical domain packages (ADR-011, ADR-012)."
---

# LARIS Twelve-Layer Architectural Specification

This document defines the formal boundaries, responsibilities, inputs, outputs, invariants, and failure modes for each of the twelve architectural layers in LARIS.

---

## Layer 0: Data Governance & Corpus Foundation
- **Primary Responsibility:** Authoritative ingestion of permitted scientific and natural text, strict provenance auditing, license compliance, text sanitation, and leakage-proof dataset partitioning.
- **Key Subcomponents:**
  - `License & Provenance Auditor`: Verifies redistribution and training permissions.
  - `Unicode & Math Normalizer`: Repairs encoding, normalizes whitespace, LaTeX symbols, and SI units.
  - `Corpus Deduplicator`: Identifies duplicate papers, preprints vs. camera-ready versions.
  - `Leakage-Proof Partition Engine`: Splits data into Train/Validation/Test partitions strictly across document and author boundaries.
- **Inputs:** Raw scientific papers (PDF, HTML, LaTeX, TXT) and public open datasets.
- **Outputs:** Versioned, clean, partitioned text corpora with cryptographic provenance manifests.
- **Invariants:** No unverified or proprietary data enters the training pipeline; test sets must remain unvisited during training.

---

## Layer 1: Language Foundation
- **Primary Responsibility:** Tokenization, lexical analysis, subword modeling, and base sequence representation trained entirely in-house.
- **Key Subcomponents:**
  - `Scientific Tokenizer`: In-house Byte-level BPE or Unigram tokenizer optimized for STEM terminology and symbols.
  - `Morphological & Syntax Analyzer`: Part-of-speech tagger and dependency grammar parser.
  - `Sentence & Paragraph Encoder`: Compact neural encoders producing dense vector representations.
- **Inputs:** Clean text stream from Layer 0.
- **Outputs:** Token IDs, dependency trees, dense sentence embeddings.
- **Invariants:** 100% self-built weights; zero mandatory external pretrained checkpoints.

---

## Layer 2: Semantic Intelligence
- **Primary Responsibility:** Disentangling semantic equivalence, question intent, textual entailment, coreference, and discourse relations.
- **Key Subcomponents:**
  - `Paraphrase & Equivalence Classifier`: Distinguishes semantic equivalence from mere topical overlap.
  - `Natural Language Inference (NLI) Engine`: 3-way classifier (`Entailment`, `Contradiction`, `Neutral`).
  - `Scientific Coreference Resolver`: Resolves complex technical anaphora and noun-phrase chains.
  - `Discourse Connective Parser`: Identifies causal, comparative, conditional, and concessive relations.
  - `Uncertainty & Ambiguity Scorer`: Quantifies epistemic hedging and linguistic vagueness.
- **Inputs:** Sentence pairs, parsed syntax trees, and discourse spans from Layer 1.
- **Outputs:** NLI classification probabilities, coreference clusters, discourse DAGs.
- **Invariants:** High semantic similarity must NEVER be assumed to imply entailment without NLI verification.

---

## Layer 3: Scientific Language Intelligence
- **Primary Responsibility:** Extracting scientific discourse units and epistemically classifying scientific assertions independent of section headings.
- **Key Subcomponents:**
  - `Discourse Unit Extractor`: Extracts claims, methods, datasets, metrics, and experimental results.
  - `Heading-Agnostic Limitation Inferencer`: Identifies study limitations, uncalibrated instruments, and sample size caveats in unstructured narrative.
  - `Assumption & Boundary Condition Detector`: Extracts implicit physical, theoretical, or operational assumptions.
  - `STEM & EE Terminology Normalizer`: Standardizes units (e.g. $\text{GHz}$, $\text{dBm}$, $\text{nm}$) and technical nomenclature.
  - `Epistemic Status Classifier`: Classifies assertions into empirical, correlational, causal, or speculative claims.
- **Inputs:** Ingested scientific documents and Layer 2 semantic representations.
- **Outputs:** Structured `Claim`, `Method`, `Result`, `Limitation`, and `Assumption` entities.
- **Invariants:** Absence of explicit "Limitations" heading must not prevent limitation inference.

---

## Layer 4: Document Intelligence
- **Primary Responsibility:** Ingesting heterogeneous document formats, reconstructing visual reading order, and generating canonical Document Trees anchored to precise source coordinates.
- **Key Subcomponents:**
  - `Multi-Format Layout Ingestion Engine`: Ingests PDF, DOCX, HTML, TXT, and LaTeX.
  - `Reading Order & Structure Parser`: Handles multi-column layouts, footnotes, and sidebars.
  - `Table & Equation Extractor`: Parses tabular data into structured arrays and LaTeX formulas into abstract trees.
  - `Coordinate Mapper`: Maps every token and sentence to exact page and bounding box spans.
  - `Extraction Confidence Assessor`: Assigns quality and OCR confidence scores.
- **Inputs:** Raw document files.
- **Outputs:** Canonical `DocumentTree` with coordinates and extraction confidence metrics.
- **Invariants:** Every extracted sentence must retain physical source coordinates for auditability.

---

## Layer 5: Research Knowledge & Evidence Graph
- **Primary Responsibility:** Maintaining the persistent, versioned, heterogeneous knowledge graph linking papers, authors, methods, claims, evidence, and limitations.
- **Key Subcomponents:**
  - `Entity Store`: Manages `Document`, `Author`, `Method`, `Dataset`, `Metric`, `Claim`, `Evidence`.
  - `Relation Engine`: Manages typed edges (`supports`, `contradicts`, `extends`, `reproduces`, `depends_on`, `compares_with`).
  - `Epistemic Provenance Registry`: Differentiates author-stated claims from system-inferred relationships.
  - `Temporal Evolution Tracker`: Tracks scientific claims across publication publication timelines.
- **Inputs:** Entities and discourse relations from Layers 3 and 4.
- **Outputs:** Graph query interface, neighborhood subgraphs, contradiction paths.
- **Invariants:** Inferred edges must never overwrite or be conflated with author-asserted edges.

---

## Layer 6: Hybrid Hierarchical RAG
- **Primary Responsibility:** Multi-channel, depth-adaptive retrieval across lexical indexes, dense semantic vectors, claim graphs, and structured metadata.
- **Key Subcomponents:**
  - `Lexical Index (BM25)`: Fast keyword search with scientific token stemming.
  - `Dense Vector Retriever`: Embeds queries via Layer 1 encoders for semantic retrieval.
  - `Graph Traversal Engine`: Multi-hop path retrieval across the Layer 5 Evidence Graph.
  - `Multi-Stage Reranker`: Combines relevance, discourse alignment, and evidence credibility.
  - `Depth-Adaptive Controller`: Escalates retrieval from sentence $\rightarrow$ paragraph $\rightarrow$ section $\rightarrow$ paper based on epistemic uncertainty.
- **Inputs:** User research intent and sub-questions.
- **Outputs:** Ranked, calibrated evidence packages with provenance coordinates.
- **Invariants:** Retrieval must be depth-bounded to prevent context window explosion.

---

## Layer 7: Research Reasoning Engine
- **Primary Responsibility:** Cross-paper evidence synthesis, method comparison, contradiction detection, research gap identification, and hypothesis formulation.
- **Key Subcomponents:**
  - `Cross-Paper Synthesis Core`: Aligns experimental conditions and metrics across studies.
  - `Contradiction & Inconsistency Detector`: Identifies conflicting findings across papers.
  - `Gap Discovery Engine`: Evaluates candidate gaps against the 12-class gap taxonomy.
  - `Adversarial Counter-Evidence Query Engine`: Actively searches corpus to refute candidate gaps.
  - `Calibrated Gap Scorer`: Computes multidimensional gap scores (Novelty, Grounding, Feasibility, Significance, Uncertainty).
  - `Hypothesis & Validation Generator`: Produces testable hypotheses with concrete empirical validation protocols.
- **Inputs:** Evidence packages from Layer 6 and Evidence Graph subgraphs from Layer 5.
- **Outputs:** Verified research gaps, comparative matrices, and validation plans.
- **Invariants:** Global novelty must NEVER be claimed if literature coverage is bounded.

---

## Layer 8: Agent Orchestration
- **Primary Responsibility:** Coordinated execution of specialized autonomous agents using dynamic DAG planning, resource-bounded timeouts, and self-review gates.
- **Key Subcomponents:**
  - `Supervisor / Orchestrator`: High-level goal decomposition and task monitoring.
  - `Query Planner`: Translates natural language research questions into execution DAGs.
  - `Specialist Agents`: Domain-specific agents (`Language Analysis`, `Document Analysis`, `Evidence Retrieval`, `Scientific Claim`, `Synthesis`, `Gap Discovery`).
  - `Critical Reviewer / Verifier`: Adversarial agent checking evidence consistency and citation integrity.
  - `Report Composer`: Formats synthesis into structured research reports.
- **Inputs:** Research task objectives and resource budgets.
- **Outputs:** Orchestrated task outputs, execution logs, and validated research synthesis.
- **Invariants:** Agents operate strictly through typed contracts; infinite execution loops are prohibited via hard recursion ceilings.

---

## Layer 9: Adaptive Model Execution & Resource Orchestrator
- **Primary Responsibility:** Real-time hardware telemetry, selective loading and offloading of specialist weights, memory pooling, and compute routing.
- **Key Subcomponents:**
  - `Task Router`: Directs subtasks to deterministic heuristics, small models, or reasoning modules based on difficulty and budget.
  - `Weight Staging Manager`: Swaps specialist weights between GPU VRAM, host RAM, and NVMe SSD.
  - `Hardware Telemetry Monitor`: Tracks real-time VRAM allocation, host RAM, and transfer latency.
  - `Adaptive Depth Governor`: Halts computation when epistemic confidence is satisfied.
- **Inputs:** Execution DAG from Layer 8 and real-time hardware telemetry.
- **Outputs:** Managed model execution with guaranteed zero OOM crashes.
- **Invariants:** Active VRAM must remain $\le 15.0$ GB on the RTX 5070 Ti.

---

## Layer 10: Evaluation, Feedback & Policy Learning
- **Primary Responsibility:** Automated regression testing, empirical benchmarking against frozen test sets, scientific error taxonomies, and offline policy learning.
- **Key Subcomponents:**
  - `Continuous Benchmark Runner`: Evaluates performance across all 8 core capability dimensions.
  - `Scientific Error Taxonomy Logger`: Records false claims, hallucinated gaps, and coordinate mismatches.
  - `Hard-Negative Miner`: Identifies challenging sentence pairs and contradictions for iterative fine-tuning.
  - `Policy Optimizer`: Contextual bandit and reinforcement learning for agent routing—gated by deterministic reward environments.
- **Inputs:** Execution traces, expert review feedback, benchmark datasets.
- **Outputs:** Evaluation reports, updated routing policies, and curated training sets.
- **Invariants:** Reward functions based solely on surface fluency are strictly prohibited.

---

## Layer 11: Reporting & User Interface
- **Primary Responsibility:** Interactive presentation of structured research reports, evidence coordinate inspection, citation tracing, and project management.
- **Key Subcomponents:**
  - `Structured Report Generator`: Compiles evidence-first research reports as default deliverable.
  - `On-Demand Manuscript Composer`: Drafts publication-ready paper drafts only upon explicit user request.
  - `Interactive Evidence Viewer`: Enables user inspection of source PDF paragraphs and highlighted spans.
  - `Human-in-the-Loop Feedback Console`: Allows users to accept, reject, or adjust inferred relationships and gaps.
  - `Project & Corpus Manager`: Manages workspace state, document versions, and historical runs.
- **Inputs:** Synthesized findings from Layer 7 and orchestrated report from Layer 8.
- **Outputs:** Human-facing research reports, interactive visualizations, and feedback signals to Layer 10.
- **Invariants:** Every conclusion displayed must provide a clickable link to its verified evidence coordinates.

---

## 2. Conceptual Layers vs Canonical Domain Packages ([ADR-011](../adr/ADR-011-domain-based-package-refactoring.md), [ADR-012](../adr/ADR-012-elimination-of-parallel-layer-hierarchies.md))

In accordance with [ADR-011](../adr/ADR-011-domain-based-package-refactoring.md) and [ADR-012](../adr/ADR-012-elimination-of-parallel-layer-hierarchies.md), LARIS decouples its conceptual 12-layer cognitive architecture from the physical Python package layout. All parallel numbered layer directories (`src/laris/layers/layerX_*`) have been permanently retired. The conceptual architecture defines the data flow and system capabilities, while domain packages provide single, authoritative implementation locations:


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

