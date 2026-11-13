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

### 2.1 English stage-1 replacement sources (D46 / ADR-022, task T175)

The Vietnamese rows above (WIKIPEDIA-VI, VINLI, VISTS, CC100-VI-CLEAN, UIT-VIQUAD-V2) are **withdrawn from stage 1** (status `WITHDRAWN_D46`; files stay in `data/` outside Git, unused). They are replaced by the English sources below, acquired on 2026-11-14 at the owner's request (at least 20 GB, covering language modelling, inference, similarity, paraphrase, question answering and retrieval). Selection, file limits and licence notes are configuration: `configs/data/english_sources.yaml`. Counts and SHA-256 are in `data/acquisition_manifest.json`.

| Dataset ID | Role | Source | Licence | Records | Size | Status |
| :--- | :--- | :--- | :--- | ---: | ---: | :--- |
| **FINEWEB-EDU-EN** | mlm | [HuggingFaceFW/fineweb-edu](https://huggingface.co/datasets/HuggingFaceFW/fineweb-edu) | ODC-By-1.0 | 3,661,000 | 10.76 GB | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **OPENWEBTEXT-EN** | mlm | [Skylion007/openwebtext](https://huggingface.co/datasets/Skylion007/openwebtext) | CC0-1.0 | 1,202,073 | 3.63 GB | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **C4-EN** | mlm | [allenai/c4](https://huggingface.co/datasets/allenai/c4) | ODC-By-1.0 | 2,850,538 | 2.55 GB | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **GUTENBERG-EN** | mlm | [manu/project_gutenberg](https://huggingface.co/datasets/manu/project_gutenberg) | Public domain (Project Gutenberg texts) | 16,520 | 3.33 GB | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **CC-NEWS-EN** | mlm | [vblagoje/cc_news](https://huggingface.co/datasets/vblagoje/cc_news) | Not declared (CC-News crawl) | 708,241 | 1.12 GB | `DOWNLOADED` / `NEEDS_LICENSE_REVIEW` |
| **CNN-DAILYMAIL-EN** | mlm | [abisee/cnn_dailymail](https://huggingface.co/datasets/abisee/cnn_dailymail) | Apache-2.0 | 311,971 | 0.84 GB | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **XSUM-EN** | mlm | [EdinburghNLP/xsum](https://huggingface.co/datasets/EdinburghNLP/xsum) | Not declared (BBC articles) | 226,711 | 0.33 GB | `DOWNLOADED` / `NEEDS_LICENSE_REVIEW` |
| **WIKIPEDIA-SIMPLE-EN** | mlm | [wikimedia/wikipedia](https://huggingface.co/datasets/wikimedia/wikipedia) | CC-BY-SA-3.0 / GFDL | 241,787 | 0.16 GB | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **WANLI-EN** | nli | [alisawuffles/WANLI](https://huggingface.co/datasets/alisawuffles/WANLI) | CC-BY-4.0 | 107,885 | 0.03 GB | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **SCITAIL-EN** | nli | [allenai/scitail](https://huggingface.co/datasets/allenai/scitail) | Not declared (AllenAI release) | 27,026 | 0.01 GB | `DOWNLOADED` / `NEEDS_LICENSE_REVIEW` |
| **STS-COMPANION-EN** | similarity | [tasksource/sts-companion](https://huggingface.co/datasets/tasksource/sts-companion) | Apache-2.0 | 5,293 | 0.00 GB | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **STS12-TRAIN-EN** | similarity | [mteb/sts12-sts](https://huggingface.co/datasets/mteb/sts12-sts) | Not declared (SemEval-2012 release) | 2,234 | 0.00 GB | `DOWNLOADED` / `NEEDS_LICENSE_REVIEW` |
| **SICK-EN** | similarity | [RobZamp/sick](https://huggingface.co/datasets/RobZamp/sick) | CC-BY-NC-SA-3.0 | 9,840 | 0.00 GB | `DOWNLOADED` / `NEEDS_LICENSE_REVIEW` |
| **MRPC-EN** | paraphrase | [nyu-mll/glue](https://huggingface.co/datasets/nyu-mll/glue) | Other (GLUE, MSR paraphrase corpus) | 5,801 | 0.00 GB | `DOWNLOADED` / `NEEDS_LICENSE_REVIEW` |
| **ALTLEX-EN** | paraphrase | [sentence-transformers/altlex](https://huggingface.co/datasets/sentence-transformers/altlex) | Not declared (AltLex release) | 112,696 | 0.02 GB | `DOWNLOADED` / `NEEDS_LICENSE_REVIEW` |
| **SIMPLE-WIKI-EN** | paraphrase | [sentence-transformers/simple-wiki](https://huggingface.co/datasets/sentence-transformers/simple-wiki) | Not declared (Wikipedia-derived) | 102,225 | 0.02 GB | `DOWNLOADED` / `NEEDS_LICENSE_REVIEW` |
| **COCO-CAPTIONS-EN** | paraphrase | [sentence-transformers/coco-captions](https://huggingface.co/datasets/sentence-transformers/coco-captions) | Not declared (COCO captions, CC-BY-4.0 upstream annotations) | 414,010 | 0.02 GB | `DOWNLOADED` / `NEEDS_LICENSE_REVIEW` |
| **STACKEXCHANGE-DUPLICATES-EN** | paraphrase | [sentence-transformers/stackexchange-duplicates](https://huggingface.co/datasets/sentence-transformers/stackexchange-duplicates) | CC-BY-SA-4.0 (Stack Exchange data dump) | 805,504 | 0.40 GB | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **SPECTER-TRIPLETS-EN** | paraphrase | [sentence-transformers/specter](https://huggingface.co/datasets/sentence-transformers/specter) | Not declared (SPECTER citation triplets) | 684,098 | 0.06 GB | `DOWNLOADED` / `NEEDS_LICENSE_REVIEW` |
| **SQUAD-V2-EN** | qa | [rajpurkar/squad_v2](https://huggingface.co/datasets/rajpurkar/squad_v2) | CC-BY-SA-4.0 | 142,192 | 0.02 GB | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **ADVERSARIAL-QA-EN** | qa | [UCLNLP/adversarial_qa](https://huggingface.co/datasets/UCLNLP/adversarial_qa) | CC-BY-SA-4.0 | 36,000 | 0.01 GB | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **TRIVIAQA-WIKI-EN** | qa | [mandarjoshi/trivia_qa](https://huggingface.co/datasets/mandarjoshi/trivia_qa) | Not declared (TriviaQA, Apache-2.0 upstream code) | 77,582 | 2.29 GB | `DOWNLOADED` / `NEEDS_LICENSE_REVIEW` |
| **BOOLQ-EN** | qa | [google/boolq](https://huggingface.co/datasets/google/boolq) | CC-BY-SA-3.0 | 12,697 | 0.00 GB | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **DROP-EN** | qa | [ucinlp/drop](https://huggingface.co/datasets/ucinlp/drop) | CC-BY-SA-4.0 | 86,935 | 0.01 GB | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **QASC-EN** | qa | [allenai/qasc](https://huggingface.co/datasets/allenai/qasc) | CC-BY-4.0 | 9,980 | 0.00 GB | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **ARC-CHALLENGE-EN** | qa | [allenai/ai2_arc](https://huggingface.co/datasets/allenai/ai2_arc) | CC-BY-SA-4.0 | 2,590 | 0.00 GB | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **COMMONSENSEQA-EN** | qa | [tau/commonsense_qa](https://huggingface.co/datasets/tau/commonsense_qa) | MIT | 12,102 | 0.00 GB | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **NATURAL-QUESTIONS-PAIRS-EN** | retrieval | [sentence-transformers/natural-questions](https://huggingface.co/datasets/sentence-transformers/natural-questions) | CC-BY-SA-3.0 (Natural Questions) | 100,231 | 0.04 GB | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **GOOAQ-EN** | retrieval | [sentence-transformers/gooaq](https://huggingface.co/datasets/sentence-transformers/gooaq) | Apache-2.0 (GooAQ) | 3,012,496 | 0.61 GB | `VERIFIED` / `APPROVED_FOR_ACQUISITION` |
| **ELI5-EN** | retrieval | [sentence-transformers/eli5](https://huggingface.co/datasets/sentence-transformers/eli5) | Not declared (ELI5 forum answers) | 325,475 | 0.11 GB | `DOWNLOADED` / `NEEDS_LICENSE_REVIEW` |
| **YAHOO-ANSWERS-EN** | retrieval | [sentence-transformers/yahoo-answers](https://huggingface.co/datasets/sentence-transformers/yahoo-answers) | Not declared (Yahoo Answers) | 681,164 | 0.30 GB | `DOWNLOADED` / `NEEDS_LICENSE_REVIEW` |
| **MSMARCO-EN** | retrieval | [microsoft/ms_marco](https://huggingface.co/datasets/microsoft/ms_marco) | Microsoft research-only terms | 1,010,916 | 2.11 GB | `DOWNLOADED` / `NEEDS_LICENSE_REVIEW` |

**Totals:** 32 sources, 17,005,813 records, 28.79 GB (the target of at least 20 GB is met).
- `mlm`: 9,218,841 records, 22.72 GB
- `nli`: 134,911 records, 0.03 GB
- `similarity`: 17,367 records, 0.00 GB
- `paraphrase`: 2,124,334 records, 0.53 GB
- `qa`: 380,078 records, 2.34 GB
- `retrieval`: 5,130,282 records, 3.17 GB

**Licence status.** `APPROVED_FOR_ACQUISITION` means an open licence declared on the publisher card. `NEEDS_LICENSE_REVIEW` (non-commercial, undeclared or unclear: SICK, MS MARCO, CC-News, XSum, TriviaQA, SciTail, ELI5, Yahoo Answers, MRPC, STS12, AltLex, Simple-Wiki, COCO captions, SPECTER) is research-only until the owner records approval per source; no such approval exists yet. Web-derived text (FineWeb-Edu, OpenWebText, C4) is open at the compilation level; page rights stay with the publishers.

**Leakage rule (STS-B).** Extra similarity sets (STS-COMPANION, STS12 train, SICK) are filtered by `scripts/check_sts_leakage.py`: any pair sharing a normalised sentence with STS-B validation or test is dropped. Result (`reports/verification/T175-sts-leakage.json`): 14,429 clean pairs kept in `data/processed/sts_extra_en/train.parquet`; 697 STS12 pairs and 1,395 SICK pairs were removed as leaked, which confirms the check is needed. TriviaQA, SQuAD v2, DROP and other QA sets are not yet deduplicated against SQuAD v1.1 val and test (SQuAD v2 shares its articles); partitioning (T177) must do this before they are used.

**Not covered.** Scientific full text stays in stage 2 (S2ORC, T101). English STEM gold for G12 is still missing. Quality filters, deduplication against Wikipedia and token budgets are decided at partition time (T177).

---

## 3. Disaggregated Counting Units & Verified Local Counts

In strict accordance with Issue #205 and Issue #209, LARIS distinguishes between different measurement units:
1. **Supervised Task Records:** Distinct supervised input-label instances (e.g. premise-hypothesis pair, question-context triple, sentence similarity pair).
2. **General Language Clean Document Records:** Full clean encyclopedic article documents.
3. **Sentences / Text Segments:** Extracted clean paragraphs or sentences.

> **After D46 (2026-11-14):** the figures in this section are the generation-1 reconciliation, kept as history. Vietnamese counts below are withdrawn from stage 1; the current English additions and totals are in section 2.1 and in the manifest (41.07 GB and 25,321,296 samples over all tracked sources, Vietnamese included until they are removed from the manifest by T177).

### Current Local Summary (Manifest Reconciled)
- **Tracked Datasets:** 17 (VERIFIED 14, SKIPPED_TEMPORARILY 1, PROPOSED 2). Totals count `VERIFIED` + `DOWNLOADED` only.
- **Total Acquired Storage:** 12,056,063,312 bytes (~12.06 GB, strictly $< 20\text{ GB}$).
- **Total Acquired Sample Records:** **8,288,209 records** (English 4,205,734; Vietnamese 4,082,475).
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
- `VINLI`: 30,376 Vietnamese 4-label NLI pairs
- `VISTS`: 23,850 Vietnamese STS pairs (translated STS12-16, test-only)
- `STSB`: 8,628 semantic similarity pairs

### 3.1 Disaggregated Language Ledgers
- **English Track:** **4,205,734 records**
  - Supervised Task Records: 2,173,984 (`ALL-NLI`, `QUORA-DUPLICATES`, `FEVER`, `ANLI`, `SQUAD`, `HOTPOTQA`, `PAWS-WIKI`, `STSB`)
  - Clean General Documents: 2,031,750 articles (`WIKIPEDIA-EN-BOUNDED`)
- **Vietnamese Track:** **4,082,475 records**
  - Supervised Task Records: 93,795 (`UIT-VIQUAD-V2`, `VINLI`, `VISTS`)
  - Clean General Documents: 3,988,680 (`WIKIPEDIA-VI` 1,288,680 + `CC100-VI-CLEAN` 2,700,000)
- **LARIS Gold Benchmark Track:** **0 records** (formal specification `DOC-SPEC-DATA-002`; zero fabricated annotations)

---

## 4. Dedicated Semantic Similarity Coverage (Issue #205 Item 3)

Semantic similarity is explicitly represented and acquired via the **STS-B (Semantic Textual Similarity Benchmark)**:
- **Canonical Schema:** `(sentence1: str, sentence2: str, score: float)` where `score` is normalized to the continuous range `[0.0, 1.0]`.
- **Verified Record Count:** 8,628 pairs (5,749 train / 1,500 validation / 1,379 test).
- **Integrity Digest:** Verified SHA-256 digests recorded in `data/acquisition_manifest.json`.

---

## 4.1 Partition Coverage and Scope (`laris-server data partition`)

The registry tracks 17 datasets (owner decision, Issue #274). Fourteen feed the five language-encoder tasks and are partitioned into leakage-safe train/val/test splits: WIKIPEDIA-VI, WIKIPEDIA-EN-BOUNDED, CC100-VI-CLEAN (mlm); ALL-NLI, ANLI, VINLI, FEVER (nli); QUORA-DUPLICATES, PAWS-WIKI (paraphrase); STSB, VISTS (similarity); SQUAD, UIT-VIQUAD-V2, HOTPOTQA (qa). The other three are planned for the fine-tuning stage and have no data yet:

| Dataset | Status |
| :--- | :--- |
| S2ORC-STEM | `SKIPPED_TEMPORARILY`: the official API requires a key (HTTP 401). |
| LARIS-GOLD | `PROPOSED`: the internal gold benchmark is not built. |
| NATURAL-QUESTIONS | `PROPOSED`: the full dump is 42 GB; a bounded subset is planned. |

Removed from the registry because no current stage consumes them: VI-PAWS (no public Vietnamese release), UIT-VIQUAD v1.1 (superseded by UIT-VIQUAD-V2 over the same contexts), PUBLAYNET-MINI and DOCLAYNET-BOUNDED (layout), UD-EWT-EN and UD-VTB-VI (treebanks) and SCIFACT. Re-adding one requires a new acquirer, a manifest entry and a consumer.

Rows that cannot carry a real label are dropped at partition time rather than relabelled: HotpotQA questions without a located answer span (yes/no or unlocatable), UIT-ViQuAD2.0 rows whose `answer_start` does not point at the answer text (154 in train), and Quora pairs with an empty question (2). Unanswerable UIT-ViQuAD2.0 questions are kept because "no answer" is their real label. The training loader raises on any unknown label, missing score or mismatched answer offset, and a scan of all 7,999,454 partitioned rows found none.

---

## 5. Target Scale Compliance & Storage Bounds (Issue #209)

> Amended by D46: the strict 20 GB storage bound below was a generation-1 limit. The owner now requires at least 20 GB of English data; total local data is 41.07 GB (disk has room). Records below are history.

### 5.1 Requirements Verification
- **Target Scale:** $\ge 5,000,000$ and strictly $< 20,000,000$ records: **met** (8,288,209).
- **Earlier ~16.5M projection:** **not reachable with real public sources.** Published sizes of the sources are far below the projected figures (ViNLI ~30k not 1M; UIT-ViQuAD2.0 ~39.6k not 600k; FEVER 349k not 1.5M; HotpotQA 98k not 700k). No synthetic or fabricated records are added to close the gap.
- **Disk Storage Bound:** Strictly $< 20\text{ GB}$; achieved **12.06 GB**.
- **License Compliance:** `VERIFIED` datasets have approved licenses (open licenses, or owner-approved as noted above) (`CC-BY-SA-3.0/4.0`, `CC-BY-4.0`, `CC-BY-NC-4.0`, `CDLA-Permissive-1.0/2.0`, `MIT`). `DOWNLOADED` datasets await license review (see above).
- **Integrity Verification:** Every file recorded with SHA-256; CC-100 shards are written atomically and resumable.

---

## 6. Training Freeze Governance Invariant

> **MANDATORY POLICY:**  
> **NO MODEL TRAINING WAS RUN.**  
> Pretraining, continued pretraining, supervised fine-tuning, reinforcement learning, training jobs, optimizer steps, checkpoint generation, and adapter/LoRA training remain strictly frozen. All data ingestion, schema validation, and benchmark executions are read-only and validation-only.
