---
document_id: "DOC-SPEC-DATA-001"
title: "LARIS Dataset Inventory, Licensing Matrix & Scalable Sampling Specification"
document_type: "specification"
status: "APPROVED"
version: "1.1.0"
created_at: "2026-10-16"
updated_at: "2026-10-17"
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
change_summary: "Reconciled manifest totals, added STS-B / Quora / All-NLI / SQuAD inventory, corrected DocLayNet sample accounting, and established transparent 5M-<20M target gap analysis (Issue #205)."
---

# LARIS Dataset Inventory, Licensing Matrix & Scalable Sampling Specification

## 1. Executive Overview

This specification establishes the authoritative dataset inventory, licensing governance, and sampling framework for the LARIS staged learning pipeline (Milestones M11, Issues #200 and #205 / [M11-DATA-001](https://github.com/ntdev204/laris/issues/200), [M11-DATA-002](https://github.com/ntdev204/laris/issues/205)).

In accordance with [ADR-002](file:///home/thientn204/laris/docs/adr/ADR-002-self-built-language-foundation.md) and [ADR-004](file:///home/thientn204/laris/docs/adr/ADR-004-evidence-provenance-first-class.md):
- **Local-first provenance:** All data sources must have verifiable origins, immutable cryptographic digests (SHA-256), and explicit licenses.
- **English-first with Vietnamese separate:** Vietnamese datasets are budgeted and tracked as an independent curriculum.
- **OCR scope:** Printed scientific documents only. Handwriting datasets are strictly excluded.
- **Minimum floors, not caps:** The 1,000,000-sample figure for Model 1 and Model 2 represents a minimum entry floor, not a maximum ceiling or adequacy guarantee.
- **Target range:** The project target is $\ge 5,000,000$ and strictly $< 20,000,000$ valid deduplicated task records.
- **Strict training freeze:** **NO MODEL TRAINING IS RUN DURING THIS PHASE.**

---

## 2. Priority Inventory & Licensing Matrix

| Dataset ID | Full Name & Version | Canonical Source | License | Redistribution Terms & Scope | Intended Stage / Capability | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **UD-EWT-EN** | Universal Dependencies English-EWT v2.14 | [UD English](https://github.com/UniversalDependencies/UD_English-EWT) | `CC-BY-SA-4.0` | Open redistribution with attribution and ShareAlike | Stage 1: Syntax, POS, Morphology | `VERIFIED` |
| **UD-VTB-VI** | Universal Dependencies Vietnamese-VTB v2.14 | [UD Vietnamese](https://github.com/UniversalDependencies/UD_Vietnamese-VTB) | `CC-BY-SA-4.0` | Open redistribution with attribution and ShareAlike | Stage 1: Vietnamese Syntax & POS | `VERIFIED` |
| **PAWS-WIKI** | Paraphrase Adversaries from Word Scrambling (Final) | [Google Research PAWS](https://github.com/google-research-datasets/paws) | `CC-BY-4.0` | Open redistribution with attribution | Stage 1: Paraphrase & Lexical Equivalence | `VERIFIED` |
| **STSB** | Semantic Textual Similarity Benchmark | [sentence-transformers/stsb](https://huggingface.co/datasets/sentence-transformers/stsb) | `CC-BY-SA-4.0` | Open redistribution with attribution | Stage 1: Continuous Semantic Similarity [0.0–1.0] | `VERIFIED` |
| **QUORA-DUPLICATES** | Quora Question Pairs (pair-class) | [quora-duplicates](https://huggingface.co/datasets/sentence-transformers/quora-duplicates) | Quora TOS | Non-commercial research use | Stage 1: Paraphrase Equivalence Classification | `VERIFIED` |
| **ALL-NLI** | All-NLI Consolidated Corpus (SNLI + MultiNLI) | [sentence-transformers/all-nli](https://huggingface.co/datasets/sentence-transformers/all-nli) | `CC-BY-SA-4.0` | Open redistribution with attribution | Stage 1: 3-Way Natural Language Inference | `VERIFIED` |
| **SQUAD** | Stanford Question Answering Dataset v1.1 | [rajpurkar/squad](https://huggingface.co/datasets/rajpurkar/squad) | `CC-BY-SA-4.0` | Open redistribution with attribution | Stage 1: Reading Comprehension & Evidence QA | `VERIFIED` |
| **ANLI** | Adversarial Natural Language Inference v0.1 | [Meta AI ANLI](https://github.com/facebookresearch/anli) | `CC-BY-NC-4.0` | Non-commercial academic research | Stage 1: Adversarial 3-Way NLI | `VERIFIED` |
| **SCIFACT** | SciFact Scientific Claim Verification v1.0 | [AllenAI SciFact](https://github.com/allenai/scifact) | `CC-BY-4.0` (annotations) / PubMed TOS | Open research redistribution with attribution | Stage 2: Scientific Claim-Evidence NLI | `VERIFIED` |
| **UIT-VIQUAD** | UIT Vietnamese Question Answering v1.1 | [UIT-ViQuAD](https://github.com/TrungDS10/UIT-ViQuAD) | `CC-BY-NC-4.0` | Non-commercial academic research | Stage 1: Vietnamese QA & Comprehension | `VERIFIED` |
| **PUBLAYNET-MINI** | PubLayNet Layout Analysis (Validation Sample) | [IBM / PubLayNet](https://github.com/ibm-aur-nlp/PubLayNet) | `CDLA-Permissive-1.0` | Permissive data redistribution | Stage 3: Printed Document Layout Detection | `VERIFIED` |
| **DOCLAYNET-BOUNDED** | DocLayNet Document Layout Analysis v1.0 | [IBM / DocLayNet](https://github.com/DS4SD/DocLayNet) | `CDLA-Permissive-2.0` | Permissive community data license | Stage 3: 11-Class Page Layout Segmentation | `VERIFIED` (Sample) |
| **S2ORC-STEM** | Semantic Scholar Open Research Corpus (STEM Subset) | [Semantic Scholar API](https://api.semanticscholar.org/datasets/v1/release/latest/dataset/s2orc) | `ODC-BY-1.0` | Open Data Commons with attribution | Stage 2 & 4: STEM Pretraining & Structure | `SKIPPED_TEMPORARILY` |
| **WIKIPEDIA-EN-VI** | Wikimedia Foundation STEM & Article Dumps | [Wikimedia Dumps](https://dumps.wikimedia.org/) | `CC-BY-SA-4.0` | Free encyclopedia content with ShareAlike | Stage 1: Vocabulary & General LM | `PROPOSED` |
| **NATURAL-QUESTIONS** | Google Natural Questions (NQ) | [Google Research NQ](https://ai.google.com/research/NaturalQuestions) | `CC-BY-4.0` | Open redistribution with attribution | Stage 1: General Reading Comprehension | `PROPOSED` |
| **LARIS-GOLD** | LARIS Epistemic Scientific Research Benchmark | Internal Repository Project Spec | `CC-BY-4.0` | Open project benchmark | Stage 5 & 6: End-to-End Epistemic Evaluation | `PROPOSED` |

---

## 3. Disaggregated Counting Units & Verified Local Counts

In strict accordance with Issue #205, LARIS distinguishes between different measurement units:
1. **Supervised Task Records:** Distinct supervised input-label instances (e.g. premise-hypothesis pair, question-context triple, sentence similarity pair).
2. **Raw Corpus Documents:** Full unstructured documents or scientific papers.
3. **Sentences / Text Segments:** CoNLL-U annotated sentences or extracted clean paragraphs.
4. **Layout Regions / Pages:** Bounding-box annotations or layout-segmented document pages.

### Current Verified Local Summary (Manifest Reconciled)
- **Total Local Files Tracked:** 24 verified files across 12 active local directories.
- **Total Verified Storage:** 193,148,215 bytes (~193.1 MB).
- **Total Verified Task Records:** **1,786,061 records**.
  - `ALL-NLI`: 981,382 NLI pairs
  - `QUORA-DUPLICATES`: 404,290 paraphrase pairs
  - `ANLI`: 169,265 adversarial NLI pairs
  - `SQUAD`: 98,169 reading comprehension items
  - `PAWS-WIKI`: 65,401 adversarial paraphrase pairs
  - `UIT-VIQUAD`: 32,278 Vietnamese QA pairs
  - `UD-EWT-EN`: 16,622 syntax sentences
  - `STSB`: 8,628 semantic similarity pairs
  - `SCIFACT`: 6,592 claim-evidence records
  - `UD-VTB-VI`: 3,323 Vietnamese syntax sentences
  - `PUBLAYNET-MINI`: 110 layout region annotations
  - `DOCLAYNET-BOUNDED`: 1 bounded loader script (reconciled; full 80,863 pages not claimed as downloaded)

---

## 4. Dedicated Semantic Similarity Coverage (Issue #205 Item 3)

Semantic similarity is explicitly represented and acquired via the **STS-B (Semantic Textual Similarity Benchmark)**:
- **Canonical Schema:** `(sentence1: str, sentence2: str, score: float)` where `score` is normalized to the continuous range `[0.0, 1.0]`.
- **Verified Record Count:** 8,628 pairs (5,749 train / 1,500 validation / 1,379 test).
- **Integrity Digest:** Verified SHA-256 digests recorded in `data/acquisition_manifest.json`.

---

## 5. Transparent 5M–<20M Target Gap Analysis & Staged Roadmap

### 5.1 Gap Analysis
- **Project Target:** $\ge 5,000,000$ and $< 20,000,000$ verified, deduplicated task records.
- **Current Verified Local Count:** 1,786,061 task sample records.
- **Remaining Gap:** **3,213,939 records** to meet the 5M minimum entry floor.

### 5.2 Staged Acquisition Roadmap
To close the remaining gap responsibly without breaching the 20M ceiling or 20 GB disk limit, the following authorized candidate pipeline is planned:

1. **Wikimedia Official Dumps (English & Vietnamese):**
   - Source: [Wikimedia Dumps](https://dumps.wikimedia.org/) (`CC-BY-SA-4.0`).
   - Planned Yield: ~2,500,000 English clean text segments + ~800,000 Vietnamese clean text segments.
   - Storage Estimate: ~4.5 GB compressed.
2. **S2ORC Bounded STEM Subset:**
   - Source: Semantic Scholar API (`ODC-BY-1.0`).
   - Prerequisite: Partner API key configuration or pre-filtered STEM shard provisioning.
   - Planned Yield: ~1,500,000 structured section records (strictly $< 20\text{ GB}$).
3. **PubMedQA Additional Subsets:**
   - Source: [PubMedQA](https://pubmedqa.github.io/) (`MIT` / PubMed Open Access).
   - Planned Yield: 61.2k unlabeled + 211.3k artificial QA pairs (~272,500 records).
4. **Google Natural Questions (NQ-Open Subset):**
   - Source: [Google Research NQ](https://github.com/google-research-datasets/natural-questions) (`CC-BY-4.0`).
   - Planned Yield: ~307,000 evidence-grounded QA pairs.

**Total Staged Pipeline Potential:** $1,786,061 + 3,300,000 + 1,500,000 + 272,500 + 307,000 \approx 7,165,561\text{ records}$, comfortably satisfying the 5M floor while remaining safely below the 20M hard ceiling.

---

## 6. Training Freeze Governance Invariant

> **MANDATORY POLICY:**  
> **NO MODEL TRAINING WAS RUN.**  
> Pretraining, continued pretraining, supervised fine-tuning, reinforcement learning, training jobs, optimizer steps, checkpoint generation, and adapter/LoRA training remain strictly frozen. All data ingestion, schema validation, and benchmark executions are read-only and validation-only.
