---
document_id: "DOC-SPEC-MOD-001"
title: "LARIS Core Module Interface Contracts Specification"
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
  - "docs/architecture/LAYER_ARCHITECTURE.md"
  - "docs/specifications/DATA_SCHEMAS.md"
decision_references:
  - "ADR-001"
  - "ADR-002"
  - "ADR-004"
  - "ADR-006"
change_summary: "Formal specification of module contracts for the 11 core functional boundaries (A through K)."
---

# LARIS Core Module Interface Contracts Specification

## 1. Overview & Architectural Contract Standard

This document formalizes the runtime interface contracts for the 11 core architectural boundaries in LARIS (Boundaries A through K). Each boundary definition specifies the functional contract, input/output schemas, error hierarchy, performance bounds, and testing invariants required to ensure modular independence.

---

## 2. Boundary A: Corpus & Data Governance (`MOD-CORPUS-001`)
- **module_id:** `MOD-CORPUS-001` (v0.1.0)
- **Purpose:** Ingest raw scientific files, audit redistribution licenses, deduplicate documents, sanitize Unicode/LaTeX/math, and partition datasets into leakage-proof splits.
- **Non-Goals:** Does not parse document layout or extract scientific semantics.
- **Input Schema:** `RawCorpusPayload` (`file_path: Path`, `declared_license: str`, `source_venue: str`).
- **Output Schema:** `ValidatedCorpusItem` (`corpus_id: str`, `clean_text: str`, `sha256: str`, `split: Enum[TRAIN, VAL, TEST]`, `provenance_manifest: dict`).
- **Preconditions:** Source file exists and is readable; license is in allowed license registry.
- **Postconditions:** Text is UTF-8 normalized; cryptographic hash recorded; split assignment is deterministic and author-isolated.
- **Error Types:** `LicenseViolationError`, `EncodingCorruptError`, `DuplicateCorpusError`, `DataLeakageError`.
- **Resource Limits:** CPU-only, host RAM $\le 2$ GB per batch, zero GPU VRAM.
- **Determinism:** 100% deterministic given identical seed and input bytes.
- **Observability:** Structured JSON logs capturing ingested bytes, deduplication ratios, and split distributions.
- **Evaluation Metrics:** Deduplication precision, Unicode repair accuracy, zero train-test overlap.

---

## 3. Boundary B: Language Foundation (`MOD-LANG-001`)
- **module_id:** `MOD-LANG-001` (v0.1.0)
- **Purpose:** Provide in-house tokenization, morphological tagging, syntactic dependency trees, and dense sentence embeddings.
- **Non-Goals:** Does not classify high-level scientific claims or discourse relations.
- **Input Schema:** `NormalizedSentenceInput` (`text: str`, `language: str = "en"`).
- **Output Schema:** `TokenizedSentenceOutput` (`token_ids: List[int]`, `tokens: List[str]`, `embedding: List[float]`, `syntax_tree: dict`).
- **Preconditions:** Text non-empty and sanitized by Boundary A.
- **Postconditions:** Embedding length matches model dimension ($D=384$ or $D=768$); token count $\le \text{max\_sequence\_length}$.
- **Error Types:** `SequenceLengthExceededError`, `VocabularyMismatchError`, `EmbeddingDimensionMismatchError`.
- **Resource Limits:** Tier 1 model ($< 1$ GB VRAM), latency $< 20$ ms per sentence.
- **Evaluation Metrics:** Tokenizer fertility on STEM terms, embedding retrieval MRR on scientific paraphrase benchmarks.

---

## 4. Boundary C: Semantic Intelligence (`MOD-SEM-001`)
- **module_id:** `MOD-SEM-001` (v0.1.0)
- **Purpose:** Execute 3-way Natural Language Inference (NLI: Entailment, Contradiction, Neutral), detect semantic equivalence, resolve coreference, and parse discourse relations.
- **Non-Goals:** Does not evaluate empirical scientific truth across external literature.
- **Input Schema:** `SentencePairInput` (`premise: str`, `hypothesis: str`, `context_span: Optional[str]`).
- **Output Schema:** `NLIOutput` (`prediction: Enum[ENTAILMENT, CONTRADICTION, NEUTRAL]`, `probabilities: dict[str, float]`, `uncertainty_score: float`).
- **Preconditions:** Premise and hypothesis encoded via Boundary B.
- **Postconditions:** Sum of class probabilities equals $1.0 \pm 10^{-5}$; uncertainty score $\in [0, 1]$.
- **Error Types:** `UncertaintyCeilingExceededError`, `DiscourseParseError`.
- **Resource Limits:** Tier 2 model ($\le 2.0$ GB VRAM), latency $< 50$ ms per pair.
- **Invariants:** High semantic similarity score must NEVER override NLI contradiction prediction.

---

## 5. Boundary D: Scientific Language Intelligence (`MOD-SCINLP-001`)
- **module_id:** `MOD-SCINLP-001` (v0.1.0)
- **Purpose:** Extract scientific discourse units (claims, methods, metrics, results, assumptions, limitations) independent of section headers.
- **Non-Goals:** Does not perform cross-paper synthesis or ranking.
- **Input Schema:** `DocumentTree` from Boundary E.
- **Output Schema:** `DiscourseExtractionSet` (`claims: List[ClaimRecord]`, `limitations: List[LimitationRecord]`, `assumptions: List[AssumptionRecord]`, `metrics: List[MetricRecord]`).
- **Preconditions:** Valid `DocumentTree` with coordinates.
- **Postconditions:** Every extracted entity references a valid `EvidenceCoordinate`.
- **Error Types:** `ExtractionConfidenceBelowThresholdError`, `MalformedDiscourseSpanError`.
- **Evaluation Metrics:** Entity F1 score, heading-agnostic limitation detection recall $\ge 80\%$.

---

## 6. Boundary E: Document Intelligence (`MOD-DOC-001`)
- **module_id:** `MOD-DOC-001` (v0.1.0)
- **Purpose:** Ingest multi-format documents (PDF, DOCX, HTML, TXT), reconstruct visual reading order, and build the canonical hierarchical `DocumentTree` with exact coordinates.
- **Non-Goals:** Does not summarize or analyze scientific validity.
- **Input Schema:** `RawDocumentFile` (`file_path: Path`, `mime_type: str`).
- **Output Schema:** `DocumentTree` (Sections, Paragraphs, Sentences, BoundingBoxes, OCR Quality Scores).
- **Preconditions:** File exists and matches supported MIME type.
- **Postconditions:** All sentences mapped to exact physical coordinates (`page`, `char_start`, `char_end`).
- **Error Types:** `UnsupportedFormatError`, `CorruptPDFLayoutError`, `OCRLowQualityError`.
- **Resource Limits:** CPU-bound parser, RAM $\le 3$ GB per 50-page document.

---

## 7. Boundary F: Retrieval & Evidence Graph (`MOD-GRAPH-001`)
- **module_id:** `MOD-GRAPH-001` (v0.1.0)
- **Purpose:** Store, query, and traverse the persistent heterogeneous evidence graph linking documents, authors, methods, claims, and limitations.
- **Non-Goals:** Does not formulate research hypotheses.
- **Input Schema:** `GraphQueryRequest` (`query_type: Enum[NEIGHBORHOOD, CONTRADICTION_PATH, METHOD_COMPARISON]`, `target_entities: List[str]`, `max_depth: int`).
- **Output Schema:** `GraphQueryResult` (`subgraph_nodes: List[Node]`, `typed_edges: List[Edge]`, `provenance_records: List[EvidenceCoordinate]`).
- **Invariants:** Inferred edges are strictly flagged with `edge_type="INFERRED"` and never conflated with author-asserted edges.

---

## 8. Boundary G: Research Reasoning Engine (`MOD-REASON-001`)
- **module_id:** `MOD-REASON-001` (v0.1.0)
- **Purpose:** Compare experimental conditions, detect conflicting results, discover candidate research gaps against the 12-class taxonomy, and formulate validation protocols.
- **Non-Goals:** Does not directly render user UI widgets.
- **Input Schema:** `ReasoningInput` (`research_intent: str`, `evidence_subgraph: GraphQueryResult`).
- **Output Schema:** `ReasoningSynthesis` (`comparative_matrix: dict`, `conflicts: List[ConflictRecord]`, `ranked_gaps: List[ResearchGap]`, `validation_plans: List[ValidationPlan]`).
- **Preconditions:** Evidence subgraph contains verified coordinates.
- **Postconditions:** All candidate gaps evaluated against the 5 calibrated scoring dimensions; global novelty is NOT asserted if corpus is bounded.

---

## 9. Boundary H: Agent Orchestration (`MOD-ORCH-001`)
- **module_id:** `MOD-ORCH-001` (v0.1.0)
- **Purpose:** Dynamically plan, supervise, and dispatch tasks to specialist agents (`Supervisor`, `Query Planner`, `Claim Agent`, `Verifier`, `Composer`) with recursion ceilings and budget gates.
- **Non-Goals:** Does not compute model parameter weights directly.
- **Input Schema:** `ResearchGoal` (`goal_statement: str`, `resource_budget: BudgetLimits`).
- **Output Schema:** `OrchestrationResult` (`final_artifacts: dict`, `execution_trace: List[AgentStep]`, `resource_usage: dict`).
- **Invariants:** Hard recursion depth limit ($N \le 10$ steps); any cyclic loop triggers immediate graceful termination.

---

## 10. Boundary I: Adaptive Model Execution (`MOD-EXEC-001`)
- **module_id:** `MOD-EXEC-001` (v0.1.0)
- **Purpose:** Telemetry monitoring, selective loading/offloading of specialist weights between VRAM, RAM, and SSD, ensuring strict compliance with hardware budgets.
- **Non-Goals:** Does not interpret scientific claims.
- **Input Schema:** `SpecialistExecutionRequest` (`specialist_id: str`, `input_tensor_batch: Any`).
- **Output Schema:** `SpecialistExecutionResult` (`output_tensor_batch: Any`, `telemetry: TelemetrySnapshot`).
- **Invariants:** Total allocated GPU VRAM MUST NOT exceed 14.5 GB on the RTX 5070 Ti. Inactive models evicted via LRU before loading new weights.

---

## 11. Boundary J: Evaluation, Feedback & Learning (`MOD-EVAL-001`)
- **module_id:** `MOD-EVAL-001` (v0.1.0)
- **Purpose:** Execute continuous regression benchmark suites, track the scientific error taxonomy, mine hard negatives, and record policy optimization metrics.
- **Non-Goals:** Does not train models during live user interaction.
- **Input Schema:** `EvaluationRunRequest` (`benchmark_suite_id: str`, `target_checkpoint_id: str`).
- **Output Schema:** `BenchmarkReport` (`metrics_table: dict`, `regressions_detected: List[str]`, `pass_fail_status: bool`).
- **Invariants:** Benchmark datasets are frozen and immutable; zero training set contamination.

---

## 12. Boundary K: Reporting & User Interface (`MOD-REP-001`)
- **module_id:** `MOD-REP-001` (v0.1.0)
- **Purpose:** Compile and render structured research reports (default deliverable), interactive citation viewers, and on-demand manuscript drafting.
- **Non-Goals:** Does not generate unverified claims outside of synthesis results.
- **Input Schema:** `ReportGenerationRequest` (`synthesis: ReasoningSynthesis`, `output_format: Enum[REPORT, MANUSCRIPT]`).
- **Output Schema:** `ResearchReportArtifact` (`markdown_text: str`, `structured_json: dict`, `evidence_citations: List[EvidenceCoordinate]`).
- **Invariants:** Manuscript generation is executed ONLY upon explicit user command; default output is always a structured research report.
