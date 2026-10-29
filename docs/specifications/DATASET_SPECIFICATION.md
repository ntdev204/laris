---
document_id: "DOC-SPEC-DATA-001"
title: "LARIS Dataset Inventory, Licensing Matrix & Scalable Sampling Specification"
document_type: "specification"
status: "APPROVED"
version: "1.2.1"
created_at: "2026-10-16"
updated_at: "2026-10-29"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md"
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
change_summary: "Documented which of the 24 datasets are partitioned and why (Issue #264). Added acquisition logic and real sources/licenses for 7 bilingual expansion datasets (ViNLI, ViSTS, Vi-PAWS blocked, CC-100 VI, HotpotQA, FEVER, UIT-ViQuAD2.0); reconciled totals to 8,347,135 records and documented the gap versus the earlier ~16.5M projection (Issue #244)."
---

# LARIS Dataset Inventory, Licensing Matrix & Scalable Sampling Specification

## 1. Executive Overview

This specification establishes the authoritative dataset inventory, licensing governance, and sampling framework for the LARIS staged learning pipeline (Milestones M11, Issues #200 and #205 / [M11-DATA-001](https://github.com/ntdev204/laris/issues/200), [M11-DATA-002](https://github.com/ntdev204/laris/issues/205)).

In accordance with [ADR-002](../adr/ADR-002-self-built-language-foundation.md) and [ADR-004](../adr/ADR-004-evidence-provenance-first-class.md):
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
| **WIKIPEDIA-VI** | Wikimedia Official Vietnamese Wikipedia Clean Dump | [Wikimedia / Hugging Face](https://huggingface.co/datasets/wikimedia/wikipedia) | `CC-BY-SA-4.0` | Open redistribution with ShareAlike | Stage 1: Clean General Vietnamese Documents | `VERIFIED` |
| **WIKIPEDIA-EN-BOUNDED** | Wikimedia Official English Wikipedia Bounded Dump (13 Shards) | [Wikimedia / Hugging Face](https://huggingface.co/datasets/wikimedia/wikipedia) | `CC-BY-SA-4.0` | Open redistribution with ShareAlike | Stage 1: Clean General English Documents | `VERIFIED` |
| **S2ORC-STEM** | Semantic Scholar Open Research Corpus (STEM Subset) | [Semantic Scholar API](https://api.semanticscholar.org/datasets/v1/release/latest/dataset/s2orc) | `ODC-BY-1.0` | Open Data Commons with attribution | Stage 2 & 4: STEM Pretraining & Structure | `SKIPPED_TEMPORARILY` |
| **NATURAL-QUESTIONS** | Google Natural Questions (NQ) | [Google Research NQ](https://ai.google.com/research/NaturalQuestions) | `CC-BY-4.0` | Open redistribution with attribution | Stage 1: General Reading Comprehension | `PROPOSED` |
| **LARIS-GOLD** | LARIS Epistemic Scientific Research Benchmark | Internal Repository Project Spec | `CC-BY-4.0` | Open project benchmark | Stage 5 & 6: End-to-End Epistemic Evaluation | `PROPOSED` |
| **VINLI** | Vietnamese Natural Language Inference (ViNLI) | [HF presencesw/vinli_4_label](https://huggingface.co/datasets/presencesw/vinli_4_label) | Not declared by uploader | Research use only; `NEEDS_LICENSE_REVIEW` before any redistribution (upstream `vnlp/vinli` returns 404) | Stage 1: Vietnamese 3-Way NLI & Reasoning | `VERIFIED` (owner-approved) |
| **VISTS** | Vietnamese Semantic Textual Similarity (ViSTS) | [HF anti-ai/ViSTS](https://huggingface.co/datasets/anti-ai/ViSTS) | `MIT` | Open redistribution with attribution (test suites only; upstream `vnlp/vists` returns 404) | Stage 1: Vietnamese Continuous Similarity | `VERIFIED` |
| **VI-PAWS** | Vietnamese Paraphrase Adversaries (Vi-PAWS) | [PAWS-X](https://huggingface.co/datasets/google-research-datasets/paws-x) | N/A | No public Vietnamese release: PAWS-X covers de/en/es/fr/ja/ko/zh only | Stage 1: Vietnamese Adversarial Paraphrase | `BLOCKED` |
| **CC100-VI-CLEAN** | Cleaned CC-100 Vietnamese Web Corpus (bounded stream) | [CC-100](https://data.statmt.org/cc-100/) | Common Crawl Terms of Use (no dataset license) | `NEEDS_LICENSE_REVIEW`; bounded prefix of a 29.5 GB xz stream, NFC-normalized and exact-deduplicated | Stage 1: Clean General Vietnamese Documents | `VERIFIED` (owner-approved) |
| **HOTPOTQA** | HotpotQA Multi-Hop Reading Comprehension (distractor) | [HF hotpotqa/hotpot_qa](https://huggingface.co/datasets/hotpotqa/hotpot_qa) | `CC-BY-SA-4.0` | Open redistribution with ShareAlike | Stage 1 & 2: Multi-Hop Evidence Reasoning | `VERIFIED` |
| **FEVER** | Fact Extraction and VERification (FEVER) v1.0 | [FEVER Project](https://fever.ai/dataset/fever.html) | `CC-BY-SA-3.0` | Open redistribution with ShareAlike (Wikipedia-derived; not MIT) | Stage 1 & 2: Fact-Checking & Claim Verification | `VERIFIED` |
| **UIT-VIQUAD-V2** | UIT-ViQuAD 2.0 (Unanswerable QA) | [HF taidng/UIT-ViQuAD2.0](https://huggingface.co/datasets/taidng/UIT-ViQuAD2.0) | Academic research use (no SPDX license declared) | Non-commercial academic research; `NEEDS_LICENSE_REVIEW` | Stage 1: Vietnamese Unanswerable QA | `VERIFIED` (owner-approved) |

---

## 3. Disaggregated Counting Units & Verified Local Counts

In strict accordance with Issue #205 and Issue #209, LARIS distinguishes between different measurement units:
1. **Supervised Task Records:** Distinct supervised input-label instances (e.g. premise-hypothesis pair, question-context triple, sentence similarity pair).
2. **General Language Clean Document Records:** Full clean encyclopedic article documents.
3. **Sentences / Text Segments:** CoNLL-U annotated sentences or extracted clean paragraphs.
4. **Layout Regions / Pages:** Bounding-box annotations or layout-segmented document pages.

### Current Local Summary (Manifest Reconciled)
- **Tracked Datasets:** 24 (VERIFIED 20, BLOCKED 1, SKIPPED_TEMPORARILY 1, PROPOSED 2). Totals count `VERIFIED` + `DOWNLOADED` only.
- **Total Acquired Storage:** 12,092,268,300 bytes (~12.09 GB, strictly $< 20\text{ GB}$).
- **Total Acquired Sample Records:** **8,347,135 records** (English 4,229,059; Vietnamese 4,118,076).
- **License caveat:** `VINLI`, `UIT-VIQUAD-V2` and `CC100-VI-CLEAN` declare no dataset license. Their use was approved by the project owner on 2026-10-29 (`license_status = APPROVED_BY_OWNER`). This is an owner governance decision, not a legal clearance, and is recorded in each manifest entry's notes.

#### Detailed Dataset Breakdown
- `WIKIPEDIA-EN-BOUNDED`: 2,031,750 clean article documents
- `CC100-VI-CLEAN`: 2,700,000 clean web documents (streamed, deduplicated, $\ge 200$ chars; bounded subset of the 29.5 GB CC-100 Vietnamese dump)
- `WIKIPEDIA-VI`: 1,288,680 clean article documents
- `ALL-NLI`: 981,382 NLI pairs
- `QUORA-DUPLICATES`: 404,290 paraphrase pairs
- `FEVER`: 348,997 claims (311,431 train + 37,566 labelled_dev; labelled test is unreleased). Evidence references are resolved to Wikipedia sentences (`evidence_sentences.parquet`, 27,949 of 28,163 referenced sentences found); SUPPORTS/REFUTES claims become entailment/contradiction NLI pairs (train 77,139 / val 4,249 / test 4,120), NOT ENOUGH INFO is dropped
- `ANLI`: 169,265 adversarial NLI pairs
- `SQUAD`: 98,169 reading comprehension items
- `HOTPOTQA`: 97,852 multi-hop QA items (distractor train + validation)
- `PAWS-WIKI`: 65,401 adversarial paraphrase pairs
- `UIT-VIQUAD-V2`: 39,569 Vietnamese QA items incl. unanswerable (test answers not public)
- `UIT-VIQUAD`: 32,278 Vietnamese QA pairs
- `VINLI`: 30,376 Vietnamese 4-label NLI pairs
- `VISTS`: 23,850 Vietnamese STS pairs (translated STS12-16, test-only)
- `UD-EWT-EN`: 16,622 syntax sentences
- `STSB`: 8,628 semantic similarity pairs
- `SCIFACT`: 6,592 claim-evidence records
- `UD-VTB-VI`: 3,323 Vietnamese syntax sentences
- `PUBLAYNET-MINI`: 110 layout region annotations
- `DOCLAYNET-BOUNDED`: 1 bounded loader script (full 80,863 pages not claimed as downloaded)
- `VI-PAWS`: `BLOCKED`, 0 records (PAWS-X has no Vietnamese; no fabricated data)

### 3.1 Disaggregated Language Ledgers
- **English Track:** **4,229,059 records**
  - Supervised Task Records: 2,197,198 (`ALL-NLI`, `QUORA-DUPLICATES`, `FEVER`, `ANLI`, `SQUAD`, `HOTPOTQA`, `PAWS-WIKI`, `UD-EWT-EN`, `STSB`, `SCIFACT`); plus 111 layout records
  - Clean General Documents: 2,031,750 articles (`WIKIPEDIA-EN-BOUNDED`)
- **Vietnamese Track:** **4,118,076 records**
  - Supervised Task Records: 129,396 (`UIT-VIQUAD`, `UIT-VIQUAD-V2`, `VINLI`, `VISTS`, `UD-VTB-VI`)
  - Clean General Documents: 3,988,680 (`WIKIPEDIA-VI` 1,288,680 + `CC100-VI-CLEAN` 2,700,000)
- **Multimodal Document Layout Track:** **111 layout records** (`PUBLAYNET-MINI`, `DOCLAYNET-BOUNDED`)
- **LARIS Gold Benchmark Track:** **0 records** (formal specification `DOC-SPEC-DATA-002`; zero fabricated annotations)

---

## 4. Dedicated Semantic Similarity Coverage (Issue #205 Item 3)

Semantic similarity is explicitly represented and acquired via the **STS-B (Semantic Textual Similarity Benchmark)**:
- **Canonical Schema:** `(sentence1: str, sentence2: str, score: float)` where `score` is normalized to the continuous range `[0.0, 1.0]`.
- **Verified Record Count:** 8,628 pairs (5,749 train / 1,500 validation / 1,379 test).
- **Integrity Digest:** Verified SHA-256 digests recorded in `data/acquisition_manifest.json`.

---

## 4.1 Partition Coverage (`laris data partition`)

Of the 24 tracked datasets, 14 feed the five language-encoder tasks and are partitioned into leakage-safe train/val/test splits: WIKIPEDIA-VI, WIKIPEDIA-EN-BOUNDED, CC100-VI-CLEAN (mlm); ALL-NLI, ANLI, VINLI, FEVER (nli); QUORA-DUPLICATES, PAWS-WIKI (paraphrase); STSB, VISTS (similarity); SQUAD, UIT-VIQUAD-V2, HOTPOTQA (qa). The other ten are intentionally not partitioned:

| Dataset | Reason |
| :--- | :--- |
| S2ORC-STEM | Not downloaded: the official API requires a key (HTTP 401). |
| LARIS-GOLD | Not built: no pre-existing benchmark; status `PROPOSED`. |
| NATURAL-QUESTIONS | Not downloaded: the full dump is 42 GB; status `PROPOSED`. |
| VI-PAWS | `BLOCKED`: no public Vietnamese PAWS release. |
| UIT-VIQUAD | Superseded: UIT-VIQUAD-V2 is a superset over the same contexts. |
| PUBLAYNET-MINI, DOCLAYNET-BOUNDED | Layout data (110 records and one loader script), outside the language-encoder tasks. |
| UD-EWT-EN, UD-VTB-VI, SCIFACT | Data present, but no current task reads syntax treebanks or claim verification; partition when a consumer exists. |

---

## 5. Target Scale Compliance & Storage Bounds (Issue #209)

### 5.1 Requirements Verification
- **Target Scale:** $\ge 5,000,000$ and strictly $< 20,000,000$ records: **met** (8,347,135).
- **Earlier ~16.5M projection:** **not reachable with real public sources.** Published sizes of the sources are far below the projected figures (ViNLI ~30k not 1M; UIT-ViQuAD2.0 ~39.6k not 600k; FEVER 349k not 1.5M; HotpotQA 98k not 700k). No synthetic or fabricated records are added to close the gap.
- **Disk Storage Bound:** Strictly $< 20\text{ GB}$; achieved **12.09 GB**.
- **License Compliance:** `VERIFIED` datasets have approved licenses (open licenses, or owner-approved as noted above) (`CC-BY-SA-3.0/4.0`, `CC-BY-4.0`, `CC-BY-NC-4.0`, `CDLA-Permissive-1.0/2.0`, `MIT`). `DOWNLOADED` datasets await license review (see above).
- **Integrity Verification:** Every file recorded with SHA-256; CC-100 shards are written atomically and resumable.

---

## 6. Training Freeze Governance Invariant

> **MANDATORY POLICY:**  
> **NO MODEL TRAINING WAS RUN.**  
> Pretraining, continued pretraining, supervised fine-tuning, reinforcement learning, training jobs, optimizer steps, checkpoint generation, and adapter/LoRA training remain strictly frozen. All data ingestion, schema validation, and benchmark executions are read-only and validation-only.
