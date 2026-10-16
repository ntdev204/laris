---
document_id: "DOC-SPEC-DATA-001"
title: "LARIS Dataset Inventory, Licensing Matrix & Scalable Sampling Specification"
document_type: "specification"
status: "APPROVED"
version: "1.0.0"
created_at: "2026-10-16"
updated_at: "2026-10-16"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/plans/STAGED_LEARNING_PIPELINE.md"
  - "docs/research/MODEL_TRAINING_AUDIT.md"
  - "docs/research/S2ORC_SUBSET_SELECTION.md"
  - "docs/specifications/LARIS_GOLD_SPECIFICATION.md"
  - "docs/specifications/DATA_SCHEMAS.md"
decision_references:
  - "ADR-001"
  - "ADR-002"
  - "ADR-003"
  - "ADR-004"
  - "ADR-007"
  - "ADR-008"
change_summary: "Comprehensive dataset inventory, verified licensing matrix, English/Vietnamese separate tracks, scalable sample targets, and empirical acquisition status."
---

# LARIS Dataset Inventory, Licensing Matrix & Scalable Sampling Specification

## 1. Executive Overview

This specification establishes the authoritative dataset inventory, licensing governance, and sampling framework for the LARIS staged learning pipeline (Milestone M11, Issue #200 / [M11-DATA-001](https://github.com/ntdev204/laris/issues/200)).

In accordance with [ADR-002](file:///home/thientn204/laris/docs/adr/ADR-002-self-built-language-foundation.md) and [ADR-004](file:///home/thientn204/laris/docs/adr/ADR-004-evidence-provenance-first-class.md):
- **Local-first provenance:** All data sources must have verifiable origins, immutable cryptographic digests (SHA-256), and explicit licenses.
- **English-first with Vietnamese separate:** Vietnamese datasets are budgeted and tracked as an independent curriculum.
- **OCR scope:** Printed scientific documents only. Handwriting datasets are strictly excluded.
- **Minimum floors, not caps:** The 1,000,000-sample figure for Model 1 and Model 2 represents a minimum entry floor, not a maximum ceiling or adequacy guarantee.
- **Strict training freeze:** **NO MODEL TRAINING IS RUN DURING THIS PHASE.**

---

## 2. Priority Shortlist Inventory & Licensing Matrix

| Dataset ID | Full Name & Version | Canonical Source | License | Redistribution Terms | Intended Stage / Capability | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **UD-EWT-EN** | Universal Dependencies English-EWT v2.14 | [UD English](https://github.com/UniversalDependencies/UD_English-EWT) | `CC-BY-SA-4.0` | Open redistribution with attribution and ShareAlike | Stage 1: Syntax, POS, Morphology | `VERIFIED` |
| **UD-VTB-VI** | Universal Dependencies Vietnamese-VTB v2.14 | [UD Vietnamese](https://github.com/UniversalDependencies/UD_Vietnamese-VTB) | `CC-BY-SA-4.0` | Open redistribution with attribution and ShareAlike | Stage 1: Vietnamese Syntax & POS | `VERIFIED` |
| **PAWS-WIKI** | Paraphrase Adversaries from Word Scrambling (Final) | [Google Research PAWS](https://github.com/google-research-datasets/paws) | `CC-BY-4.0` | Open redistribution with attribution | Stage 1: Paraphrase & Semantic Equivalence | `VERIFIED` |
| **ANLI** | Adversarial Natural Language Inference v0.1 | [Meta AI ANLI](https://github.com/facebookresearch/anli) | `CC-BY-NC-4.0` | Non-commercial academic research | Stage 1: 3-Way Adversarial NLI | `VERIFIED` |
| **SCIFACT** | SciFact Scientific Claim Verification v1.0 | [AllenAI SciFact](https://github.com/allenai/scifact) | `CC-BY-4.0` | Open research redistribution with attribution | Stage 2: Scientific Claim-Evidence NLI | `VERIFIED` |
| **UIT-VIQUAD** | UIT Vietnamese Question Answering v1.1 | [UIT-ViQuAD](https://github.com/TrungDS10/UIT-ViQuAD) | `CC-BY-NC-4.0` | Non-commercial academic research | Stage 1: Vietnamese QA & Comprehension | `VERIFIED` |
| **PUBLAYNET-MINI** | PubLayNet Layout Analysis (Validation Sample) | [IBM / PubLayNet](https://github.com/ibm-aur-nlp/PubLayNet) | `CDLA-Permissive-1.0` | Permissive data redistribution | Stage 3: Printed Document Layout Detection | `VERIFIED` |
| **DOCLAYNET-BOUNDED** | DocLayNet Document Layout Analysis v1.0 | [IBM / DocLayNet](https://github.com/DS4SD/DocLayNet) | `CDLA-Permissive-2.0` | Permissive community data license | Stage 3: 11-Class Page Layout Segmentation | `VERIFIED` |
| **S2ORC-STEM** | Semantic Scholar Open Research Corpus (STEM Subset) | [Semantic Scholar API](https://api.semanticscholar.org/datasets/v1/release/latest/dataset/s2orc) | `ODC-BY-1.0` | Open Data Commons with attribution | Stage 2 & 4: STEM Pretraining & Structure | `SKIPPED_TEMPORARILY` |
| **WIKIPEDIA-EN-VI** | Wikimedia Foundation STEM & Article Dumps | [Wikimedia Dumps](https://dumps.wikimedia.org/) | `CC-BY-SA-4.0` | Free encyclopedia content with ShareAlike | Stage 1: Vocabulary & General LM | `PROPOSED` |
| **NATURAL-QUESTIONS** | Google Natural Questions (NQ) | [Google Research NQ](https://ai.google.com/research/NaturalQuestions) | `CC-BY-4.0` | Open redistribution with attribution | Stage 1: General Reading Comprehension | `PROPOSED` |
| **LARIS-GOLD** | LARIS Epistemic Scientific Research Benchmark | Internal Repository Project Spec | `CC-BY-4.0` | Open project benchmark | Stage 5 & 6: End-to-End Epistemic Evaluation | `PROPOSED` |

---

## 3. Disaggregated Language Curriculum: English vs Vietnamese

In compliance with Issue #200 requirements, English and Vietnamese tracks are budgeted, measured, and stored independently:

### 3.1 English Track
- **Universal Dependencies English-EWT:** 16,622 annotated sentences (train: 12,543, dev: 2,002, test: 2,077). Provides gold syntactic dependency trees and POS tags.
- **PAWS-Wiki (Final Labeled):** 65,401 sentence pairs (train: 49,401, dev: 8,000, test: 8,000). Probes sensitivity to word order and syntax.
- **ANLI (Adversarial NLI):** 162,865 premise-hypothesis pairs across Rounds R1, R2, and R3.
- **SciFact:** 1,409 scientific claims linked to 5,183 cited biomedical abstracts.
- **PubLayNet / DocLayNet:** Document layout bounding boxes across 11 visual layout classes.

### 3.2 Vietnamese Track
- **Universal Dependencies Vietnamese-VTB:** 3,000 sentences (train: 1,400, dev: 800, test: 800). Provides universal dependencies and morphological features for Vietnamese text.
- **UIT-ViQuAD:** 23,074 question-answer pairs over 5,108 Wikipedia paragraphs. Evaluates extractive reading comprehension and passage grounding in Vietnamese.
- **Vietnamese Wikipedia (Targeted):** Planned acquisition for general vocabulary coverage ($>150,000$ articles).

---

## 4. Scalable Sampling Targets (Beyond the 1M Floor)

The 1,000,000-sample threshold is an entry planning floor. The target allocation matrix across granular capability units is defined below:

```text
Model 1 (Language & STEM Understanding):
  - General Language LM:        500,000 – 1,000,000 clean documents
  - Syntactic / POS Trees:      200,000 – 400,000 sentences
  - Paraphrase & Similarity:    300,000 – 600,000 sentence pairs
  - General 3-Way NLI:          500,000 – 1,000,000 pairs
  - Reading Comprehension:      250,000 – 500,000 QA triples
  - STEM Domain Literature:     400,000 – 800,000 open-access papers
  - Total Target:               2,500,000 – 5,000,000 samples

Model 2 (Reasoning & Verification):
  - Multi-Hop Evidence QA:      400,000 – 800,000 grounded pairs
  - Multi-Premise NLI:          500,000 – 1,000,000 triples
  - Claim Refutation / Conflicts: 250,000 – 500,000 opposing pairs
  - Evidence Sufficiency:       250,000 – 400,000 abstention sets
  - 12-Class Gap Taxonomy:      250,000 – 500,000 annotated instances
  - Total Target:               1,650,000 – 3,200,000 samples

Scientific OCR & Manuscript:
  - Page Layouts:               250,000 – 500,000 pages (DocLayNet / PubLayNet)
  - Line-Level Transcriptions:  2,000,000 – 5,000,000 text lines
```

---

## 5. Storage & Provenance Invariants

1. **Storage Isolation:**
   - Raw datasets reside in `data/raw/<dataset_id>/` and are excluded from Git commits via `.gitignore`.
   - Immutable acquisition metadata is tracked in `data/acquisition_manifest.json`.
2. **Leakage Prevention:**
   - Splitting must enforce group isolation by document ID or author group. Sentences or paragraphs originating from the same source document must never cross train/validation/test partitions.
3. **Training Freeze Invariant:**
   - **NO MODEL TRAINING WAS RUN.** No pretraining, fine-tuning, optimizer steps, or checkpoint generation were executed.
