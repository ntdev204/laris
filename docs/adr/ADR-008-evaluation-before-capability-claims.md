---
document_id: "DOC-ADR-008"
title: "ADR-008: Empirical Evaluation and Benchmark Gates Preceding Capability Claims"
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
  - "docs/testing/TEST_STRATEGY.md"
  - "docs/testing/BENCHMARK_PROTOCOL.md"
decision_references:
  - "ADR-008"
change_summary: "Established requirement for reproducible benchmark evaluation before asserting system capabilities or milestones."
---

# ADR-008: Empirical Evaluation and Benchmark Gates Preceding Capability Claims

## Metadata
- **ADR ID:** ADR-008
- **Status:** ACCEPTED
- **Date Decided:** 2026-10-15
- **Decision Owner:** LARIS Architecture Team
- **Target Layers:** Layer 10 (Evaluation & Learning), Testing Strategy

## 1. Context and Problem Statement
In machine learning and AI research, unverified claims of "superior accuracy", "robust reasoning", or "comprehensive understanding" are pervasive. In an autonomous scientific research system, relying on subjective impressions, superficial fluency, or handpicked cherry-picked demonstrations leads to dangerous overconfidence and false discoveries.

LARIS requires an uncompromising policy where capability claims must be supported by empirical, reproducible benchmarks prior to being accepted or advanced through milestone gates.

## 2. Decision
1. **No Capability Claims Without Benchmarks:** No module, model, skill, or agent SHALL be documented or reported as possessing a capability (e.g. "understands paraphrase", "infers limitations accurately", "discovers valid gaps") without citing a reproducible benchmark experiment.
2. **Standard Capability Dimensions:** Capabilities MUST be evaluated against dedicated benchmark suites covering:
   - Paraphrase and semantic equivalence.
   - Natural Language Inference (NLI) and contradiction detection.
   - Fine-grained claim, metric, and limitation extraction.
   - Multi-paper cross-study synthesis coherence.
   - Gap validity and non-triviality against wider literature.
   - Citation accuracy and zero hallucination tolerance.
   - Physical hardware efficiency (peak VRAM, RAM, transfer latency).
3. **Leakage Prevention:** Benchmark evaluation sets MUST be strictly separated from training data by document, author venue, and temporal split.
4. **Frozen Test Harnesses:** Evaluation datasets and scoring protocols MUST be placed under version control and frozen to prevent goalpost-shifting during optimization.
5. **Human and Expert Review:** Automated metrics MUST be paired with expert qualitative review gates before high-level reasoning capabilities (Layers 7, 8) are certified.

## 3. Alternatives Considered
1. **Ad-Hoc Qualitative Inspection (Spot-Checking):**
   *Rejected because:* Blind to regressions, susceptible to cherry-picking, and lacks statistical significance.
2. **Sole Reliance on LLM-as-a-Judge:**
   *Rejected because:* External LLMs suffer from circular biases, favor verbosity over empirical truth, and violate offline local-first governance.

## 4. Consequences
### 4.1. Positive
- High confidence in the factual correctness and stability of system components.
- Clear, unambiguous criteria for advancing through development milestones.
- Early detection of regressions when modifying specialist models or orchestration rules.

### 4.2. Negative & Trade-offs
- Upfront effort required to construct and curate clean scientific evaluation datasets.
- Milestone advancement is strictly gated by empirical results, preventing premature release announcements.

## 5. Risks and Mitigations
| Risk | Severity | Mitigation Strategy |
| :--- | :--- | :--- |
| Overfitting to specific benchmark suites (Goodhart's Law) | Medium | Maintain held-out challenge splits and incorporate periodic adversarial hard-negative additions. |
| Scarcity of labeled scientific NLI and gap data | High | Curate clean synthetic and semi-automated datasets using strict programmatic rules and expert validation in Layer 0. |

## 6. Validation and Acceptance Criteria
- [ ] Milestone exit criteria in `docs/plans/ROADMAP.md` include explicit quantitative benchmark score gates.
- [ ] Capability assertions in documentation reference explicit experiment reports in `artifacts/benchmark_reports/`.
