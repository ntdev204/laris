---
document_id: "DOC-RES-AUDIT-001"
title: "LARIS Implementation Audit: Model Training vs Deterministic Baselines"
document_type: "research"
status: "APPROVED"
version: "1.0.0"
created_at: "2026-10-16"
updated_at: "2026-10-16"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/plans/IMPLEMENTATION_ROADMAP.md"
  - "docs/plans/BACKLOG.md"
  - "docs/architecture/LAYER_ARCHITECTURE.md"
  - "docs/specifications/MODULE_CONTRACTS.md"
decision_references:
  - "ADR-002"
  - "ADR-008"
change_summary: "Comprehensive audit of existing codebase modules distinguishing genuine trained neural weights from deterministic, lexical, and heuristic baselines."
---

# LARIS Implementation Audit: Model Training vs Deterministic Baselines

## 1. Executive Summary

In accordance with [ADR-002](file:///home/thientn204/laris/docs/adr/ADR-002-self-built-language-foundation.md), [ADR-008](file:///home/thientn204/laris/docs/adr/ADR-008-evaluation-before-capability-claims.md), and GitHub Issue #199 ([M11-TRAIN-000](https://github.com/ntdev204/laris/issues/199)), this audit provides a rigorous, code-level inventory of all implemented components across the twelve architectural layers.

**Core Finding:**
Across all 84 source modules and 898 passing unit/contract tests, **zero neural models have undergone weight optimization, pretraining, fine-tuning, or checkpoint training**. All current operational capabilities rely entirely on deterministic algorithms, lexical indexing, heuristic rule sets, and calibrated statistical fallbacks.

No module marked `DONE` in Milestones M1 through M10 contains learned neural weights. This distinction is crucial to prevent ungrounded capability claims and to establish an authentic baseline for Milestone M11.

---

## 2. Layer-by-Layer Implementation Audit

| Layer / Module ID | Declared Role | Actual Implementation Mechanism | Real Trained Weights? | Status Classification |
| :--- | :--- | :--- | :--- | :--- |
| **Layer 0** (`MOD-CORPUS-001`) | Corpus Ingestion & Data Governance | Deterministic Unicode/math normalization, exact SHA-256 deduplication, grouped hash-partitioning. | No | Fully Deterministic / Rule-Based |
| **Layer 1** (`MOD-LANG-001`) | Scientific Tokenizer & Vocab | Greedy longest-prefix / BPE-style dictionary matching from predefined vocabulary list. | No | Algorithmic / Lexical Dictionary |
| **Layer 1** (`MOD-LANG-002`) | Compact Sentence Encoder | Hash-based random projection with lexical bag-of-words / BM25 term weighting. | No | Heuristic Projection Baseline |
| **Layer 1** (`MOD-LANG-003`) | Training Reproducibility & Lineage | Manifest serialization, SHA-256 state tracking, and mock checkpoint generation. | No | Governance & Lineage Harness |
| **Layer 2** (`MOD-SEM-001`) | 3-Way Scientific NLI | Keyword contradiction rules, lexical negation detectors, and calibrated overlap scoring. | No | Heuristic / Calibrated Rule Engine |
| **Layer 3** (`MOD-SCINLP-001`) | Scientific Discourse Extraction | Regex patterns, section-cue dictionaries, and epistemic modal marker matching. | No | Lexical Pattern Matching |
| **Layer 4 / 5** (`MOD-GRAPH-001`) | Evidence Knowledge Graph | SQLite relational schema with indexed node and edge queries. | No | Relational Database Storage |
| **Layer 6** (`MOD-RETR-001`) | Multi-Channel Hybrid Retrieval | Reciprocal Rank Fusion (RRF) combining lexical BM25 and projection adapters. | No | Statistical Algorithmic Fusion |
| **Layer 7** (`MOD-RSN-001`) | Research Gap Discovery | Rule-based 12-class matrix synthesis and contradiction detection. | No | Rule-Based Matrix Engine |
| **Layer 8** (`MOD-ORCH-001`) | Multi-Agent Orchestration | State-machine DAG execution, cycle detection, and token budget governance. | No | Deterministic Runtime Workflow |
| **Layer 9** (`MOD-EXEC-001`) | Adaptive Local Execution | Memory headroom governor and LRU cache for sequential module loading. | No | Hardware Telemetry & Resource Manager |
| **Layer 10** (`MOD-EVAL-001`) | Feedback & Benchmark Gates | Test runner comparing predictions against gold JSON fixtures. | No | Verification Framework |
| **Layer 11** (`MOD-PROD-001`) | Structured Reporting & Packaging | Coordinate-enforced Markdown serializer and template manuscript composer. | No | Template Serialization Engine |

---

## 3. Detailed Component Findings

### 3.1 Tokenization & Language Representations (`src/laris/layers/layer1_language`)
- `STEMSubwordTokenizer` in `tokenizer.py`: Implements dictionary-based greedy token matching. It checks vocabulary constraints and calculates subword fertility against test text. It does not train subword merges from raw text corpora via unigram/BPE optimization.
- `CompactSentenceEncoder` in `encoder.py`: Employs a deterministic hashing trick to map tokens into fixed-dimensional vectors, optionally passed through an unoptimized projection matrix.

### 3.2 Semantic Inference & Natural Language Inference (`src/laris/layers/layer2_semantic`)
- `ScientificNLIEngine` in `engine.py`: Computes lexical overlap, negation detection, and numeric divergence. It classifies sentence pairs into `ENTAILMENT`, `CONTRADICTION`, or `NEUTRAL` using thresholded heuristic scores.
- `ConfidenceCalibrator` in `calibration.py`: Applies monotonic piecewise linear or sigmoid scaling to heuristic scores, verified via Brier score and expected calibration error (ECE).

### 3.3 Scientific Discourse & Limitation Extraction (`src/laris/layers/layer3_scinlp`)
- `DiscourseExtractor` and `LimitationExtractor` in `extractor.py` and `limitations.py`: Search for epistemic markers (`"however"`, `"limited by"`, `"small sample size"`, `"further research is needed"`). While heading-independent, they do not utilize sequence-labeling or attention-based neural architectures.

### 3.4 Hybrid Retrieval & Evidence Graph (`src/laris/layers/layer5_graph`, `layer6_retrieval`)
- Graph storage is an embedded SQLite database (`sqlite_adapter.py`) managing `EvidenceNode` and `EvidenceEdge` records.
- Retrieval combines BM25 and dense adapters via rank-constant reciprocal fusion ($RRF$). Dense scores are derived from the unoptimized hash encoder.

---

## 4. Gap Analysis for Staged Learning

To transition from the current deterministic baseline to genuine learned models, the following capabilities must be established in strict sequence:
1. **General Language Foundation (Stage 1):** Corpus acquisition, subword vocabulary training, token representations, language modeling, and supervised tasks (NLI, QA, syntax, coreference, similarity) covering both English and Vietnamese.
2. **Scientific Language Specialization (Stage 2):** Domain adaptation on scientific literature, scientific NLI, claim-evidence reasoning, and discourse parsing.
3. **Scientific OCR (Stage 3):** Optical character recognition on printed scientific papers, layout segmentation, formula/table transcription, and non-destructive post-correction.
4. **OCR-Coupled Manuscript Learning (Stage 4):** End-to-end manuscript understanding operating on OCR outputs.
5. **Architectural Integration (Stage 5):** Replacement of heuristic modules with trained model interfaces while preserving existing contracts and hardware constraints.

---

## 5. Audit Conclusion

The existing LARIS codebase constitutes a verified, complete **deterministic and architectural skeleton**. All contracts, interfaces, schemas, and governance rules are operational and rigorously tested. 

**Model training has not begun.** Milestone M11 establishes the required governance, data acquisition, and domain package refactoring to enable future model training phases under strict empirical oversight.
