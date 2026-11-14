---
document_id: "DOC-SPEC-DATA-001"
title: "LARIS Dataset Inventory, Licensing Matrix & Scalable Sampling Specification"
document_type: "specification"
status: "APPROVED"
version: "1.4.0"
created_at: "2026-10-16"
updated_at: "2026-11-14"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md"
  - "docs/archive/S2ORC_SUBSET_SELECTION.md"
  - "docs/specifications/LARIS_GOLD_SPECIFICATION.md"
  - "docs/specifications/DATA_SCHEMAS.md"
decision_references:
  - "ADR-001"
  - "ADR-002"
  - "ADR-003"
  - "ADR-004"
  - "ADR-007"
  - "ADR-008"
  - "ADR-022"
change_summary: "D46 / ADR-022 (2026-11-14): English-only stage 1; Vietnamese datasets withdrawn and deleted; 32 English replacement sources added; storage bound raised. Earlier: Registry narrowed from 24 to 17 datasets (14 active, 3 planned; Issue #274). Added acquisition logic and real sources/licenses for 7 bilingual expansion datasets (ViNLI, ViSTS, Vi-PAWS blocked, CC-100 VI, HotpotQA, FEVER, UIT-ViQuAD2.0); reconciled totals to 8,347,135 records and documented the gap versus the earlier ~16.5M projection (Issue #244)."
---

# LARIS Dataset Inventory, Licensing Matrix & Scalable Sampling Specification

## 1. Executive Overview

This specification establishes the authoritative dataset inventory, licensing governance, and sampling framework for the LARIS staged learning pipeline (Milestones M11, Issues #200 and #205 / [M11-DATA-001](https://github.com/ntdev204/laris/issues/200), [M11-DATA-002](https://github.com/ntdev204/laris/issues/205)).

In accordance with [ADR-002](../adr/ADR-002-self-built-language-foundation.md) and [ADR-004](../adr/ADR-004-evidence-provenance-first-class.md):
- **Local-first provenance:** All data sources must have verifiable origins, immutable cryptographic digests (SHA-256), and explicit licenses.
- **English only (D46 / ADR-022):** stage 1 trains on English data only. The Vietnamese datasets were withdrawn and deleted from disk on 2026-11-14; Vietnamese reaches the model through a translation layer, not through training data.
- **OCR scope:** Printed scientific documents only. Handwriting datasets are strictly excluded.
- **Minimum floors, not caps:** The 1,000,000-sample figure for Model 1 and Model 2 represents a minimum entry floor, not a maximum ceiling or adequacy guarantee.
- **Target range:** at least $5,000,000$ valid deduplicated task records; the former upper bound of $20,000,000$ is lifted because document-level MLM text is counted in documents, not tasks (D46).
- **Strict training freeze:** **NO MODEL TRAINING IS RUN DURING THIS PHASE.**

---

## 2. Priority Inventory & Licensing Matrix

| Dataset ID | Full Name & Version | Canonical Source | License | Redistribution Terms & Scope | Intended Stage / Capability | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **PAWS-WIKI** | Paraphrase Adversaries from Word Scrambling (Final) | [Google Research PAWS](https://github.com/google-research-datasets/paws) | `CC-BY-4.0` | Open redistribution with attribution | Stage 1: Paraphrase & Lexical Equivalence | `VERIFIED` |
| **STSB** | Semantic Textual Similarity Benchmark | [sentence-transformers/stsb](https://huggingface.co/datasets/sentence-transformers/stsb) | `CC-BY-SA-4.0` | Open redistribution with attribution | Stage 1: Continuous Semantic Similarity [0.0–1.0] | `VERIFIED` |
| **QUORA-DUPLICATES** | Quora Question Pairs (pair-class) | [quora-duplicates](https://huggingface.co/datasets/sentence-transformers/quora-duplicates) | Quora TOS | Non-commercial research use | Stage 1: Paraphrase Equivalence Classification | `VERIFIED` |
| **ALL-NLI** | All-NLI Consolidated Corpus (SNLI + MultiNLI) | [sentence-transformers/all-nli](https://huggingface.co/datasets/sentence-transformers/all-nli) | `CC-BY-SA-4.0` | Open redistribution with attribution | Stage 1: 3-Way Natural Language Inference | `VERIFIED` |
| **SQUAD** | Stanford Question Answering Dataset v1.1 | [rajpurkar/squad](https://huggingface.co/datasets/rajpurkar/squad) | `CC-BY-SA-4.0` | Open redistribution with attribution | Stage 1: Reading Comprehension & Evidence QA | `VERIFIED` |
| **ANLI** | Adversarial Natural Language Inference v0.1 | [Meta AI ANLI](https://github.com/facebookresearch/anli) | `CC-BY-NC-4.0` | Non-commercial academic research | Stage 1: Adversarial 3-Way NLI | `VERIFIED` |
| **WIKIPEDIA-VI** | Wikimedia Official Vietnamese Wikipedia Clean Dump | [Wikimedia / Hugging Face](https://huggingface.co/datasets/wikimedia/wikipedia) | `CC-BY-SA-4.0` | Open redistribution with ShareAlike | Stage 1: Clean General Vietnamese Documents | `WITHDRAWN_D46` (data deleted) |
| **WIKIPEDIA-EN-BOUNDED** | Wikimedia Official English Wikipedia Bounded Dump (13 Shards) | [Wikimedia / Hugging Face](https://huggingface.co/datasets/wikimedia/wikipedia) | `CC-BY-SA-4.0` | Open redistribution with ShareAlike | Stage 1: Clean General English Documents | `VERIFIED` |
| **S2ORC-STEM** | Semantic Scholar Open Research Corpus (STEM Subset) | [Semantic Scholar API](https://api.semanticscholar.org/datasets/v1/release/latest/dataset/s2orc) | `ODC-BY-1.0` | Open Data Commons with attribution | Stage 2 & 4: STEM Pretraining & Structure | `SKIPPED_TEMPORARILY` |
| **NATURAL-QUESTIONS** | Google Natural Questions (NQ) | [Google Research NQ](https://ai.google.com/research/NaturalQuestions) | `CC-BY-4.0` | Open redistribution with attribution | Stage 1: General Reading Comprehension | `PROPOSED` |
| **LARIS-GOLD** | LARIS Epistemic Scientific Research Benchmark | Internal Repository Project Spec | `CC-BY-4.0` | Open project benchmark | Stage 5 & 6: End-to-End Epistemic Evaluation | `PROPOSED` |
| **VINLI** | Vietnamese Natural Language Inference (ViNLI) | [HF presencesw/vinli_4_label](https://huggingface.co/datasets/presencesw/vinli_4_label) | Not declared by uploader | Research use only; `NEEDS_LICENSE_REVIEW` before any redistribution (upstream `vnlp/vinli` returns 404) | Stage 1: Vietnamese 3-Way NLI & Reasoning | `WITHDRAWN_D46` (data deleted) |
| **VISTS** | Vietnamese Semantic Textual Similarity (ViSTS) | [HF anti-ai/ViSTS](https://huggingface.co/datasets/anti-ai/ViSTS) | `MIT` | Open redistribution with attribution (test suites only; upstream `vnlp/vists` returns 404) | Stage 1: Vietnamese Continuous Similarity | `WITHDRAWN_D46` (data deleted) |
| **CC100-VI-CLEAN** | Cleaned CC-100 Vietnamese Web Corpus (bounded stream) | [CC-100](https://data.statmt.org/cc-100/) | Common Crawl Terms of Use (no dataset license) | `NEEDS_LICENSE_REVIEW`; bounded prefix of a 29.5 GB xz stream, NFC-normalized and exact-deduplicated | Stage 1: Clean General Vietnamese Documents | `WITHDRAWN_D46` (data deleted) |
| **HOTPOTQA** | HotpotQA Multi-Hop Reading Comprehension (distractor) | [HF hotpotqa/hotpot_qa](https://huggingface.co/datasets/hotpotqa/hotpot_qa) | `CC-BY-SA-4.0` | Open redistribution with ShareAlike | Stage 1 & 2: Multi-Hop Evidence Reasoning | `VERIFIED` |
| **FEVER** | Fact Extraction and VERification (FEVER) v1.0 | [FEVER Project](https://fever.ai/dataset/fever.html) | `CC-BY-SA-3.0` | Open redistribution with ShareAlike (Wikipedia-derived; not MIT) | Stage 1 & 2: Fact-Checking & Claim Verification | `VERIFIED` |
| **UIT-VIQUAD-V2** | UIT-ViQuAD 2.0 (Unanswerable QA) | [HF taidng/UIT-ViQuAD2.0](https://huggingface.co/datasets/taidng/UIT-ViQuAD2.0) | Academic research use (no SPDX license declared) | Non-commercial academic research; `NEEDS_LICENSE_REVIEW` | Stage 1: Vietnamese Unanswerable QA | `WITHDRAWN_D46` (data deleted) |

### 2.1 English stage-1 replacement sources (D46 / ADR-022, T175)

Acquired 2026-11-14 from `configs/data/english_sources.yaml` (endpoints, file selection and licence notes live there). Licences are the publisher's declaration on the dataset card; `NEEDS_LICENSE_REVIEW` means non-commercial, undeclared or unclear, and those sources stay research-only until the owner approves them. Roles: `mlm` = masked-language text, `nli`, `similarity` (graded), `paraphrase` (positive pairs unless labelled), `qa`, `retrieval` (question-passage pairs).

| Dataset ID | Role | Source | Licence | Records | GB | Status |
| :--- | :--- | :--- | :--- | ---: | ---: | :--- |
| **FINEWEB-EDU-EN** | mlm | [HuggingFaceFW/fineweb-edu](https://huggingface.co/datasets/HuggingFaceFW/fineweb-edu) | ODC-By-1.0 | 3,661,000 | 10.76 | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **OPENWEBTEXT-EN** | mlm | [Skylion007/openwebtext](https://huggingface.co/datasets/Skylion007/openwebtext) | CC0-1.0 | 1,202,073 | 3.63 | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **C4-EN** | mlm | [allenai/c4](https://huggingface.co/datasets/allenai/c4) | ODC-By-1.0 | 2,850,538 | 2.55 | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **GUTENBERG-EN** | mlm | [manu/project_gutenberg](https://huggingface.co/datasets/manu/project_gutenberg) | Public domain (Project Gutenberg texts) | 16,520 | 3.33 | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **CC-NEWS-EN** | mlm | [vblagoje/cc_news](https://huggingface.co/datasets/vblagoje/cc_news) | Not declared (CC-News crawl) | 708,241 | 1.12 | `VERIFIED` / `APPROVED_BY_OWNER` |
| **CNN-DAILYMAIL-EN** | mlm | [abisee/cnn_dailymail](https://huggingface.co/datasets/abisee/cnn_dailymail) | Apache-2.0 | 311,971 | 0.84 | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **XSUM-EN** | mlm | [EdinburghNLP/xsum](https://huggingface.co/datasets/EdinburghNLP/xsum) | Not declared (BBC articles) | 226,711 | 0.33 | `VERIFIED` / `APPROVED_BY_OWNER` |
| **WIKIPEDIA-SIMPLE-EN** | mlm | [wikimedia/wikipedia](https://huggingface.co/datasets/wikimedia/wikipedia) | CC-BY-SA-3.0 / GFDL | 241,787 | 0.16 | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **WANLI-EN** | nli | [alisawuffles/WANLI](https://huggingface.co/datasets/alisawuffles/WANLI) | CC-BY-4.0 | 107,885 | 0.03 | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **SCITAIL-EN** | nli | [allenai/scitail](https://huggingface.co/datasets/allenai/scitail) | Not declared (AllenAI release) | 27,026 | 0.01 | `VERIFIED` / `APPROVED_BY_OWNER` |
| **STS-COMPANION-EN** | similarity | [tasksource/sts-companion](https://huggingface.co/datasets/tasksource/sts-companion) | Apache-2.0 | 5,293 | 0.00 | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **STS12-TRAIN-EN** | similarity | [mteb/sts12-sts](https://huggingface.co/datasets/mteb/sts12-sts) | Not declared (SemEval-2012 release) | 2,234 | 0.00 | `VERIFIED` / `APPROVED_BY_OWNER` |
| **SICK-EN** | similarity | [RobZamp/sick](https://huggingface.co/datasets/RobZamp/sick) | CC-BY-NC-SA-3.0 | 9,840 | 0.00 | `VERIFIED` / `APPROVED_BY_OWNER` |
| **MRPC-EN** | paraphrase | [nyu-mll/glue](https://huggingface.co/datasets/nyu-mll/glue) | Other (GLUE, MSR paraphrase corpus) | 5,801 | 0.00 | `VERIFIED` / `APPROVED_BY_OWNER` |
| **ALTLEX-EN** | paraphrase | [sentence-transformers/altlex](https://huggingface.co/datasets/sentence-transformers/altlex) | Not declared (AltLex release) | 112,696 | 0.02 | `VERIFIED` / `APPROVED_BY_OWNER` |
| **SIMPLE-WIKI-EN** | paraphrase | [sentence-transformers/simple-wiki](https://huggingface.co/datasets/sentence-transformers/simple-wiki) | Not declared (Wikipedia-derived) | 102,225 | 0.02 | `VERIFIED` / `APPROVED_BY_OWNER` |
| **COCO-CAPTIONS-EN** | paraphrase | [sentence-transformers/coco-captions](https://huggingface.co/datasets/sentence-transformers/coco-captions) | Not declared (COCO captions, CC-BY-4.0 upstream annotations) | 414,010 | 0.02 | `VERIFIED` / `APPROVED_BY_OWNER` |
| **STACKEXCHANGE-DUPLICATES-EN** | paraphrase | [sentence-transformers/stackexchange-duplicates](https://huggingface.co/datasets/sentence-transformers/stackexchange-duplicates) | CC-BY-SA-4.0 (Stack Exchange data dump) | 805,504 | 0.40 | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **SPECTER-TRIPLETS-EN** | paraphrase | [sentence-transformers/specter](https://huggingface.co/datasets/sentence-transformers/specter) | Not declared (SPECTER citation triplets) | 684,098 | 0.06 | `VERIFIED` / `APPROVED_BY_OWNER` |
| **SQUAD-V2-EN** | qa | [rajpurkar/squad_v2](https://huggingface.co/datasets/rajpurkar/squad_v2) | CC-BY-SA-4.0 | 142,192 | 0.02 | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **ADVERSARIAL-QA-EN** | qa | [UCLNLP/adversarial_qa](https://huggingface.co/datasets/UCLNLP/adversarial_qa) | CC-BY-SA-4.0 | 36,000 | 0.01 | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **TRIVIAQA-WIKI-EN** | qa | [mandarjoshi/trivia_qa](https://huggingface.co/datasets/mandarjoshi/trivia_qa) | Not declared (TriviaQA, Apache-2.0 upstream code) | 77,582 | 2.29 | `VERIFIED` / `APPROVED_BY_OWNER` |
| **BOOLQ-EN** | qa | [google/boolq](https://huggingface.co/datasets/google/boolq) | CC-BY-SA-3.0 | 12,697 | 0.00 | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **DROP-EN** | qa | [ucinlp/drop](https://huggingface.co/datasets/ucinlp/drop) | CC-BY-SA-4.0 | 86,935 | 0.01 | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **QASC-EN** | qa | [allenai/qasc](https://huggingface.co/datasets/allenai/qasc) | CC-BY-4.0 | 9,980 | 0.00 | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **ARC-CHALLENGE-EN** | qa | [allenai/ai2_arc](https://huggingface.co/datasets/allenai/ai2_arc) | CC-BY-SA-4.0 | 2,590 | 0.00 | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **COMMONSENSEQA-EN** | qa | [tau/commonsense_qa](https://huggingface.co/datasets/tau/commonsense_qa) | MIT | 12,102 | 0.00 | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **NATURAL-QUESTIONS-PAIRS-EN** | retrieval | [sentence-transformers/natural-questions](https://huggingface.co/datasets/sentence-transformers/natural-questions) | CC-BY-SA-3.0 (Natural Questions) | 100,231 | 0.04 | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **GOOAQ-EN** | retrieval | [sentence-transformers/gooaq](https://huggingface.co/datasets/sentence-transformers/gooaq) | Apache-2.0 (GooAQ) | 3,012,496 | 0.61 | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **ELI5-EN** | retrieval | [sentence-transformers/eli5](https://huggingface.co/datasets/sentence-transformers/eli5) | Not declared (ELI5 forum answers) | 325,475 | 0.11 | `VERIFIED` / `APPROVED_BY_OWNER` |
| **YAHOO-ANSWERS-EN** | retrieval | [sentence-transformers/yahoo-answers](https://huggingface.co/datasets/sentence-transformers/yahoo-answers) | Not declared (Yahoo Answers) | 681,164 | 0.30 | `VERIFIED` / `APPROVED_BY_OWNER` |
| **MSMARCO-EN** | retrieval | [microsoft/ms_marco](https://huggingface.co/datasets/microsoft/ms_marco) | Microsoft research-only terms | 1,010,916 | 2.11 | `VERIFIED` / `APPROVED_BY_OWNER` |

Similarity sources pass `scripts/check_sts_leakage.py` before use: of 17,363 candidate pairs, 2,092 shared a sentence with STS-B validation or test and were dropped, 842 were duplicates, leaving 14,429 pairs in `data/processed/sts_extra_en/train.parquet` (`reports/verification/T175-sts-leakage.json`).

---

## 3. Disaggregated Counting Units & Verified Local Counts

Units: (1) supervised task records (a labelled pair or question), (2) general language documents, (3) text segments. Since D46 every counted record is English.

### Current Local Summary (manifest reconciled 2026-11-14)
- **Tracked datasets:** 50; five Vietnamese datasets are `WITHDRAWN_D46` (data deleted, zero counted).
- **Stage-1 English data on disk:** 33.0 GB in 42 datasets, **21,219,097 records** (S2ORC stage-1 shards excluded: they belong to stage 2).
- **MLM text:** about 11.8 billion tokens (characters divided by 4.2; an estimate until the new tokenizer exists) from FineWeb-Edu, English Wikipedia, OpenWebText, C4, Gutenberg, CC-News, CNN/DailyMail, Simple Wikipedia, XSum.
- **License caveat:** 14 sources with a non-commercial, undeclared or unclear licence (CC-News, XSum, SICK, MRPC, SciTail, TriviaQA, MS MARCO, Yahoo Answers, ELI5, STS12, AltLex, Simple-Wiki, COCO captions, SPECTER) were **approved by the owner on 2026-11-14** (`APPROVED_BY_OWNER`). This is an owner governance decision for research use, not a legal clearance; no redistribution.

### 3.1 Language ledger
- **English track:** 21,219,097 records; supervised task records and retrieval pairs plus document text as listed in section 2 and 2.1.
- **Vietnamese track:** withdrawn (D46). Vietnamese reaches the model through a translation layer, which has its own future gate.
- **LARIS-GOLD track:** 0 records; gold sources follow D47 (public human-labelled sets, otherwise LLM labels marked `label_source: llm`).

---

## 4. Dedicated Semantic Similarity Coverage

Graded similarity: STS-B (8,628 pairs: 5,749 train / 1,500 validation / 1,379 test; the only gate set, G05) plus 14,429 extra pairs after the leakage check (STS companion sets, STS12 train, SICK). Extra pairs never contain a sentence from STS-B validation or test; the check is a test, not an assumption. Graded labels are scaled to [0, 1].

---

## 4.1 Partition Coverage and Scope

Partitioned (leakage-safe train/val/test, `data/processed`, manifest `task_splits_manifest.json`, 32 datasets, T177 and T178):
- **mlm:** English Wikipedia, FineWeb-Edu, OpenWebText, C4, Gutenberg, CC-News, CNN/DailyMail, XSum, Simple Wikipedia. Documents are split 98/1/1 by a hash of their id, cut into passages of at most 4,000 characters (the loader keeps only the first `seq_len` tokens of a record) and exact duplicates are dropped across sources and against English Wikipedia. Train passages: about 13.5 million from the new sources plus 1.99 million Wikipedia articles.
- **nli:** ALL-NLI, ANLI, FEVER, WANLI (107,885 pairs pooled, 90/5/5 by pair hash), SciTail (labels `entails` / `neutral`).
- **paraphrase:** Quora, PAWS, MRPC.
- **similarity:** STS-B (gate set) and 14,429 extra pairs (`sts_extra_en`, train only).
- **qa:** SQuAD, HotpotQA, SQuAD v2 and AdversarialQA. Rows whose article title or context is in the SQuAD v1 validation or test partition are removed (11,873 from SQuAD v2, 6,000 from AdversarialQA), so G06 and G07 stay clean.

- **retrieval (T178):** GooAQ, Natural Questions, MS MARCO (selected passages only), ELI5, Yahoo Answers, Stack Exchange duplicates, SPECTER (anchor and cited title), AltLex, Simple-Wiki and COCO captions: 6.50 M query/positive pairs (6.37 M train), 98/1/1 by a hash of the query (symmetric sources by connected component of texts), in-batch negatives only, texts cut at 4,000 characters. Duplicate pairs are dropped (321,314, mostly SPECTER triplets that share an anchor and a cited title). Removed as leakage (6,472 pairs): any side equal to a SQuAD v1 validation/test question or paragraph, an STS-B validation/test sentence, a SciFact claim or title, or a positive sharing an eight-word window with a SQuAD v1 held-out paragraph or a SciFact abstract. `scripts/check_retrieval_leakage.py` rescans the output (report `reports/verification/T178-retrieval-leakage.json`): 0 held-out hits, 0 queries in two splits within a source, 96 across sources (same query text, different sources, not a held-out set). No SciFact claim is used for training. Licences stay as in section 2.1; MS MARCO, ELI5, Yahoo, SPECTER, AltLex, Simple-Wiki and COCO remain `license_approved: false`.

Acquired but **not partitioned**: TriviaQA, BoolQ, DROP, QASC, ARC, CommonsenseQA. Planned for later stages: S2ORC-STEM and science sources (stage 2), PDF sources (stage 3), LARIS-GOLD (D47).

Web text may still contain passages that also appear in evaluation sets (for example SQuAD contexts quoted from Wikipedia); exact-duplicate removal covers only identical documents, so near-duplicate contamination is not excluded and no number here says otherwise.

---

## 5. Target Scale Compliance & Storage Bounds

- **Scale:** stage-1 English data is 21,219,097 records, above the floor of 5,000,000 (the earlier upper bound is lifted, section 1).
- **Storage:** 33.0 GB of stage-1 English data, above the 20 GB the owner asked for on 2026-11-14 (the earlier strict 20 GB ceiling is lifted).
- **Integrity:** every file has a SHA-256 in `data/acquisition_manifest.json`; downloads are resumable and written to `.part` files first.
- **Not claimed:** no number here says the data is sufficient for any gate.

---

## 6. Training Freeze Governance Invariant

> **MANDATORY POLICY:**  
> **NO MODEL TRAINING WAS RUN.**  
> Pretraining, continued pretraining, supervised fine-tuning, reinforcement learning, training jobs, optimizer steps, checkpoint generation, and adapter/LoRA training remain strictly frozen. All data ingestion, schema validation, and benchmark executions are read-only and validation-only.
