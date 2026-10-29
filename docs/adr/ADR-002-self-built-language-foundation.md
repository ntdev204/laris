---
document_id: "DOC-ADR-002"
title: "ADR-002: Self-Built Language Foundation & Exclusion of Mandatory Pretrained LLMs"
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
  - "docs/research/LANGUAGE_AND_MODEL_STRATEGY.md"
decision_references:
  - "ADR-002"
change_summary: "Enforced self-built model foundation principle and prohibited mandatory pretrained LLM dependencies."
---

# ADR-002: Self-Built Language Foundation & Exclusion of Mandatory Pretrained LLMs

## Metadata
- **ADR ID:** ADR-002
- **Status:** ACCEPTED
- **Date Decided:** 2026-10-15
- **Decision Owner:** LARIS Architecture Team
- **Target Layers:** Layer 0 (Corpus Foundation), Layer 1 (Language Foundation), Layer 2 (Semantic Intelligence)

## 1. Context and Problem Statement
Modern RAG systems typically wrap off-the-shelf open-source pretrained foundation LLMs (e.g. LLaMA, Mistral, Qwen) or proprietary API endpoints. While convenient for rapid prototyping, this introduces fundamental epistemic and engineering flaws:
1. Complete lack of data provenance regarding the pretraining corpus, risking licensing violations and unknown training-test contamination.
2. Inability to optimize internal representations for specialized scientific discourse, technical notations, and domain-specific semantic relations.
3. Excessive parameter bloat (7B–70B parameters) leading to severe local VRAM exhaustion.
4. Vulnerability to upstream architectural shifts and uncalibrated hallucinatory behaviors.

## 2. Decision
1. **Tier 1 Independence:** The foundational natural language stack of LARIS SHALL NOT adopt pre-existing open or closed pretrained language models as an architectural dependency.
2. **In-House Core Linguistic Components:** LARIS SHALL develop, train, and maintain its own core NLP components, specifically:
   - Domain-optimized tokenizers and subword models.
   - Lexical and syntactic representation models.
   - Sentence and paragraph encoders.
   - Semantic equivalence and paraphrase classifiers.
   - Natural Language Inference (NLI) models.
   - Discourse relation and argumentative structure analyzers.
3. **Pragmatic Hybrid Methods:** "Self-built" does NOT require that every component must be a deep neural network. Statistical algorithms, formal grammar parsers, deterministic heuristics, graph models, and domain ontologies SHALL be leveraged wherever they offer superior interpretability, efficiency, and robustness.
4. **Strict Audit Trail:** Every training corpus, data source, license, preprocessing pipeline, and model checkpoint MUST maintain a cryptographically verifiable provenance record.
5. **Exception Governance:** Any future proposal to benchmark or incorporate an external open-weight model MUST be submitted as an independent RFC/ADR with explicit empirical justification and formal review.

## 3. Alternatives Considered
1. **Pretrained Base Model Fine-Tuning (e.g. LLaMA-3-8B / Mistral-7B):**
   *Rejected because:* Fails provenance requirements, consumes disproportionate VRAM on a 16GB GPU, and bypasses foundational scientific language modeling.
2. **Generic Embeddings (e.g. standard open-source sentence transformers):**
   *Rejected as core dependency because:* Off-the-shelf embedding models conflate topical similarity with semantic equivalence and lack fine-tuned calibration for scientific claim polarity.

## 4. Consequences
### 4.1. Positive
- Full computational and intellectual property ownership over all model weights.
- Absolute clarity regarding training data licensing, hygiene, and evaluation splits.
- Purpose-built compact architectures (e.g. 50M–350M parameters) tailored precisely to local hardware limits.
- Precise calibration of epistemic uncertainty and scientific discourse structures.

### 4.2. Negative & Trade-offs
- Substantial upfront engineering effort required to build datasets, tokenizers, and training pipelines.
- Slower initial time-to-first-prototype compared to wrapping existing off-the-shelf models.
- Requires rigorous benchmark suites to independently validate language understanding capability.

## 5. Risks and Mitigations
| Risk | Severity | Mitigation Strategy |
| :--- | :--- | :--- |
| Insufficient general world knowledge in small self-built models | Medium | Supplement neural encoders with explicit structured ontologies, external knowledge graphs, and hybrid retrieval (Layer 5 & 6). |
| High training time on single-workstation hardware | Medium | Target compact specialist architectures (<350M parameters) and domain-specific contrastive learning objectives rather than general autoregressive pretraining. |

## 6. Validation and Acceptance Criteria
- [ ] Tokenizer, sentence encoder, and NLI model codebases reside natively in `src/laris/` with zero third-party pretrained weights loaded.
- [ ] Every model checkpoint in `artifacts/checkpoints/` has an associated provenance manifest referencing Layer 0 dataset versions.
- [ ] Models demonstrate superior or comparable performance on in-domain scientific NLI and claim extraction against established baselines.
