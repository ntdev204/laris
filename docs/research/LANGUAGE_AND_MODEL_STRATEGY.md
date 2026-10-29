---
document_id: "DOC-RES-LANG-001"
title: "Research Strategy: Language Foundation, Local Models and Semantic Intelligence"
document_type: "research"
status: "DRAFT"
version: "0.2.0"
created_at: "2026-10-15"
updated_at: "2026-10-29"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/archive/IDEA.md"
  - "docs/architecture/SELECTIVE_COMPUTATION.md"
  - "docs/research/SCIENTIFIC_NLP.md"
decision_references:
  - "ADR-002"
  - "ADR-003"
  - "ADR-001"
  - "ADR-005"
change_summary: "Consolidates the language foundation, local model strategy and semantic intelligence research notes."
---

# Research Strategy: Language Foundation, Local Models and Semantic Intelligence

Research direction for the self-built language foundation, local training under the hardware envelope, and relational semantics.

## 1. Self-Built Language Foundation and Encoders

### 1. Executive Research Objective

To engineer an in-house natural language processing foundation tailored specifically to STEM and scientific discourse without depending on general-purpose, off-the-shelf foundation models.

---

### 2. Tokenization & Subword Modeling

Standard tokenizers trained on generic web corpora (e.g. GPT-2/4, standard BERT) suffer severe subword fragmentation when processing scientific formulas, SI units, and electrical engineering notations (e.g. splitting `GaAsFET` or `14.2 GHz` into 4–6 erratic fragments).

#### Candidate Algorithms for Milestone M1 Evaluation:
1. **Custom Byte-Level BPE (Byte-Pair Encoding):** Trained on sanitized scientific corpora, preserving mathematical symbols and Greek letters as atomic tokens.
2. **Unigram Language Model Tokenizer (SentencePiece formulation):** Provides probabilistic subword regularizations beneficial for technical compounds.
3. **Target Vocabulary Budget:** 32,000 to 50,000 subwords, balanced between STEM terminology fertility and embedding parameter size.

---

### 3. Compact Sentence & Paragraph Encoders

#### Target Architecture:
- **Parameter Footprint:** 50M to 125M parameters (e.g., 6–12 transformer encoder layers, hidden dimension 384 or 768).
- **Inductive Biases:** Bidirectional attention with rotary position embeddings (RoPE) or ALiBi for length extrapolation up to 2048 tokens.
- **Pretraining Objectives:**
  - Masked Language Modeling (MLM) with scientific whole-word and phrase masking.
  - Contrastive Sentence Representation learning using scientific paragraph co-occurrence and citation graph topology.

---

### 4. Evaluation Protocol & Milestones
- **Fertility Benchmark:** Average number of subwords generated per technical term across IEEE and arXiv abstracts (target: $\le 1.4$ tokens/word).
- **Paraphrase Retrieval MRR:** Mean Reciprocal Rank on scientific statement retrieval.

---

## 2. Local Model Training and Specialist Adaptation

### 1. Feasibility Analysis under Hardware Envelope

Target Hardware:
- GPU: NVIDIA RTX 5070 Ti (16 GB VRAM, $\sim 350 - 450$ TFLOPs FP16/BF16 tensor compute).
- Host RAM: 32 GB DDR5.
- CPU: Intel Core i5-14600KF.

#### Pretraining Realism:
- Training a 7B general foundation LLM from scratch requires $\sim 2\times 10^{23}$ FLOPs ($\sim 100,000$ GPU-hours on an RTX 5070 Ti), which is physically intractable.
- Conversely, training **compact specialist models (50M–150M parameters)** on curated scientific domain corpora (1B–5B tokens) requires only $30 - 100$ GPU hours, completely feasible on the local workstation.

---

### 2. Training Pipeline & Parameter Targets

| Specialist Module | Target Params | Objective / Architecture | Training Compute Est. |
| :--- | :--- | :--- | :--- |
| Scientific Tokenizer | N/A (Vocab: 40k) | Byte-level BPE / Unigram on clean corpus. | $< 1$ hour CPU |
| Core STEM Encoder | 60M–110M | RoPE Transformer, Masked Language Modeling + Contrastive. | $\sim 48 - 72$ hours GPU |
| Scientific NLI Head | 15M (on encoder) | 3-way classification on scientific claim pairs. | $\sim 6 - 12$ hours GPU |
| Claim/Discourse Extractor | 20M (on encoder) | Token sequence labeling & boundary span classification. | $\sim 8 - 16$ hours GPU |

---

## 3. Semantic Intelligence and Relational Logic

### 1. Disentangling Topical Similarity from Semantic Equivalence

A critical failure of standard vector embeddings is treating sentences with opposite meanings as highly similar due to shared topical vocabulary:
- *Sentence A:* "The alloy exhibited high tensile strength under extreme temperature."
- *Sentence B:* "The alloy suffered brittle fracture and failed under extreme temperature."

A generic cosine similarity search assigns these sentences an overlap of $\sim 0.88$. However, in scientific discourse, they represent direct empirical contradictions.

LARIS addresses this by training a specialized **Natural Language Inference (NLI)** head operating alongside dense embeddings to verify logical entailment, neutral overlap, and contradiction.

---

### 2. Scientific Coreference & Discourse Parsing
- **Complex Technical Coreference:** Resolving multi-token nominal phrases (e.g. "the proposed deep recurrent architecture", "this model", "the network under evaluation").
- **Discourse Relation Modeling:** Parsing Penn Discourse Treebank (PDTB) relations (Causal, Concessive, Contrast, Temporal) using fine-grained classification heads on sentence pairs.
