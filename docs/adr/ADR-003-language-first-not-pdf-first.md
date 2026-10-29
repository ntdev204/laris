---
document_id: "DOC-ADR-003"
title: "ADR-003: Language-First and Document-Agnostic Processing over PDF-First Design"
document_type: "adr"
status: "ACCEPTED"
version: "1.0.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/archive/IDEA.md"
  - "docs/research/SCIENTIFIC_NLP.md"
  - "docs/specifications/MODULE_CONTRACTS.md"
decision_references:
  - "ADR-003"
change_summary: "Adopted language-first representation hierarchy and document-agnostic scientific discourse processing."
---

# ADR-003: Language-First and Document-Agnostic Processing over PDF-First Design

## Metadata
- **ADR ID:** ADR-003
- **Status:** ACCEPTED
- **Date Decided:** 2026-10-15
- **Decision Owner:** LARIS Architecture Team
- **Target Layers:** Layer 1 (Language Foundation), Layer 2 (Semantic Intelligence), Layer 3 (Scientific NLP), Layer 4 (Document Intelligence)

## 1. Context and Problem Statement
Many scientific AI tools adopt a "PDF-first" architecture: they parse PDF visual bounding boxes, chunk text into fixed token windows, and rely heavily on explicit section headers (such as "Methods", "Results", "Discussion", or "Limitations") or keyword queries.

This approach fails catastrophically when:
1. Research papers omit explicit headings (e.g. limitations are discussed subtly in the narrative or discussion section).
2. OCR or multi-column layout extraction disrupts visual reading order.
3. The underlying AI lacks deep linguistic grounding, confusing topical lexical overlap with logical entailment or contradiction.
4. Input documents arrive in varied formats (HTML, LaTeX, DOCX, TXT) that lack PDF-specific visual metadata.

## 2. Decision
1. **Language-First Primacy:** LARIS SHALL establish foundational linguistic and semantic competence (Layers 1, 2, and 3) prior to and independent of document layout parsing.
2. **Document-Agnostic Representation:** Documents from any format (PDF, DOCX, HTML, TXT) SHALL be normalized into an abstract, hierarchical **Document Tree** (`Document -> Section -> Subsection -> Paragraph -> Sentence -> Token/Discourse Unit`).
3. **Heading-Agnostic Scientific Discourse Inference:** Extraction of scientific claims, experimental methods, quantitative results, assumptions, and limitations MUST operate on semantic discourse cues, grammatical voice, modal verbs, and epistemic markers, rather than relying on brittle section title regexes or keywords.
4. **Decoupled Document Parsing:** Document layout parsing (Layer 4) is treated strictly as an ingestion adapter that populates the Document Tree while preserving exact source coordinates (page, paragraph, character span) for evidence traceability.

## 3. Alternatives Considered
1. **PDF-Centric Chunking (e.g. LangChain PDFLoader + 500-token chunks):**
   *Rejected because:* Slices sentences across arbitrary boundaries, severs discourse relations, and loses structural hierarchy.
2. **Rule-Based Heading Section Splitter:**
   *Rejected because:* Breaks on unstructured preprints, letters, short communications, and non-standard conference formats that omit formal section titles.

## 4. Consequences
### 4.1. Positive
- Universal ingestion capability across diverse document formats.
- High resilience to non-standard paper formatting, missing headers, and varied publishing styles.
- Ability to infer implicit limitations and assumptions buried inside general discussion paragraphs.

### 4.2. Negative & Trade-offs
- Requires developing sophisticated discourse unit classifiers and sentence-level semantic parsers.
- Ingestion pipeline requires a multi-stage normalization step before text is available for reasoning.

## 5. Risks and Mitigations
| Risk | Severity | Mitigation Strategy |
| :--- | :--- | :--- |
| Disrupted reading order in multi-column PDFs | Medium | Implement layout-aware geometric reading order reconstructors in Layer 4 and validate with structural extraction tests. |
| Ingestion latency overhead | Low | Decouple ingestion into asynchronous background workers and cache parsed Document Trees on SSD. |

## 6. Validation and Acceptance Criteria
- [ ] Claim and limitation extraction models achieve $\ge 80\%$ recall on scientific papers where section headers have been deliberately stripped.
- [ ] System successfully parses identical research text from PDF, HTML, and Markdown formats into isomorphic Document Trees.
