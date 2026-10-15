---
document_id: "DOC-RES-LANG-001"
title: "Research Strategy: Self-Built Language Foundation & Encoders"
document_type: "research"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/IDEA.md"
  - "docs/research/SEMANTIC_INTELLIGENCE.md"
  - "docs/research/LOCAL_MODEL_STRATEGY.md"
decision_references:
  - "ADR-002"
  - "ADR-003"
change_summary: "Research strategy for custom scientific tokenization, vocabulary construction, and base encoder architectures."
---

# Research Strategy: Self-Built Language Foundation & Encoders

## 1. Executive Research Objective

To engineer an in-house natural language processing foundation tailored specifically to STEM and scientific discourse without depending on general-purpose, off-the-shelf foundation models.

---

## 2. Tokenization & Subword Modeling

Standard tokenizers trained on generic web corpora (e.g. GPT-2/4, standard BERT) suffer severe subword fragmentation when processing scientific formulas, SI units, and electrical engineering notations (e.g. splitting `GaAsFET` or `14.2 GHz` into 4–6 erratic fragments).

### Candidate Algorithms for Milestone M1 Evaluation:
1. **Custom Byte-Level BPE (Byte-Pair Encoding):** Trained on sanitized scientific corpora, preserving mathematical symbols and Greek letters as atomic tokens.
2. **Unigram Language Model Tokenizer (SentencePiece formulation):** Provides probabilistic subword regularizations beneficial for technical compounds.
3. **Target Vocabulary Budget:** 32,000 to 50,000 subwords, balanced between STEM terminology fertility and embedding parameter size.

---

## 3. Compact Sentence & Paragraph Encoders

### Target Architecture:
- **Parameter Footprint:** 50M to 125M parameters (e.g., 6–12 transformer encoder layers, hidden dimension 384 or 768).
- **Inductive Biases:** Bidirectional attention with rotary position embeddings (RoPE) or ALiBi for length extrapolation up to 2048 tokens.
- **Pretraining Objectives:**
  - Masked Language Modeling (MLM) with scientific whole-word and phrase masking.
  - Contrastive Sentence Representation learning using scientific paragraph co-occurrence and citation graph topology.

---

## 4. Evaluation Protocol & Milestones
- **Fertility Benchmark:** Average number of subwords generated per technical term across IEEE and arXiv abstracts (target: $\le 1.4$ tokens/word).
- **Paraphrase Retrieval MRR:** Mean Reciprocal Rank on scientific statement retrieval.
