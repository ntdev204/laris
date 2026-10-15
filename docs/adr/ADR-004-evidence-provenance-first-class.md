---
document_id: "DOC-ADR-004"
title: "ADR-004: Evidence Provenance & Epistemic Traceability as First-Class Citizens"
document_type: "adr"
status: "ACCEPTED"
version: "1.0.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/IDEA.md"
  - "docs/architecture/EVIDENCE_AND_PROVENANCE.md"
  - "docs/specifications/DATA_SCHEMAS.md"
decision_references:
  - "ADR-004"
change_summary: "Established end-to-end evidence provenance and epistemic classification standards."
---

# ADR-004: Evidence Provenance & Epistemic Traceability as First-Class Citizens

## Metadata
- **ADR ID:** ADR-004
- **Status:** ACCEPTED
- **Date Decided:** 2026-10-15
- **Decision Owner:** LARIS Architecture Team
- **Target Layers:** Layer 3 (Scientific NLP), Layer 5 (Evidence Graph), Layer 7 (Reasoning Engine), Layer 11 (Reporting)

## 1. Context and Problem Statement
Generative AI and traditional language models are notorious for producing plausible-sounding fabrications ("hallucinations"), attributing non-existent statements to real authors, and presenting speculative conjectures as proven facts. In scientific research, an unsupported claim or misattributed citation can invalidate downstream experimental designs and compromise academic credibility.

LARIS requires an uncompromising epistemological architecture where every synthesized assertion can be rigorously traced to its physical empirical origin.

## 2. Decision
1. **Mandatory Provenance Anchoring:** Every extracted claim, experimental metric, boundary condition, and conclusion in LARIS MUST be permanently anchored to an immutable `EvidenceCoordinate` object specifying:
   - `document_id` and document version checksum.
   - Exact location: page number, section index, paragraph index, and sentence character spans.
   - Extracted verbatim snippet or numerical value.
2. **Strict Epistemic Classification:** The reasoning engine and report generator MUST explicitly classify every scientific proposition into one of seven formal epistemic categories:
   - `DIRECT_AUTHOR_CLAIM`: Explicitly stated by the author in the paper narrative.
   - `EMPIRICALLY_SUPPORTED_FINDING`: Supported by concrete experimental data, tables, or figures.
   - `MULTI_SOURCE_SYNTHESIS`: Deduced by LARIS across two or more independent studies.
   - `HYPOTHESIS`: Theoretical conjecture proposed for validation.
   - `INSUFFICIENT_EVIDENCE`: Evaluated, but current corpus data cannot confirm or refute.
   - `CONFLICTING_EVIDENCE`: Empirical contradictions exist between reputable sources.
   - `UNVERIFIABLE_ASSERTION`: Lacks methodological details or experimental validation.
3. **Automated Verification Gate:** Generated reports MUST pass an automated provenance verification check before presentation to the user. Any statement lacking an evidence citation or containing an unverified source reference is automatically flagged and rejected.
4. **Epistemic Invariants:**
   - Absence of evidence MUST NOT be reported as evidence of absence.
   - Correlation MUST NOT be transformed into causal attribution without formal identification evidence.
   - A research gap MUST NOT be asserted based solely on low keyword frequency.

## 3. Alternatives Considered
1. **Post-Hoc Citation Retrieval (e.g. standard LLM with citation prompting):**
   *Rejected because:* The LLM generates the text first and searches for matching citations post-facto, frequently citing irrelevant papers or hallucinating page numbers.
2. **Unstructured Text Snippet Citations:**
   *Rejected because:* Lacks exact character coordinates, preventing reproducible programmatic verification and UI highlighting.

## 4. Consequences
### 4.1. Positive
- 100% auditable evidence trails from synthesized report back to exact PDF/text source spans.
- Complete elimination of phantom citations and fabricated experimental claims.
- Users can click any conclusion to view the source paragraph and highlighted context.

### 4.2. Negative & Trade-offs
- Schema complexity: Every entity and relation in Layer 5 must carry extensive provenance metadata.
- Storage overhead: Increased database and graph storage requirements for coordinate indexes.

## 5. Risks and Mitigations
| Risk | Severity | Mitigation Strategy |
| :--- | :--- | :--- |
| Coordinate offset shift when documents are re-parsed | Medium | Bind coordinates to content hashes and canonical sentence IDs rather than brittle raw character offsets alone. |
| Ingestion parsing errors causing misaligned coordinate spans | Low | Implement extraction confidence scores in Layer 4 that flag low-confidence OCR regions. |

## 6. Validation and Acceptance Criteria
- [ ] 100% of claims included in final generated research reports successfully resolve to an existing source document span.
- [ ] Automated regression tests flag and fail any synthesized report that introduces an unlinked assertion.
