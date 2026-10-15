---
document_id: "DOC-RES-EVAL-001"
title: "Research Strategy: Scientific Capability Evaluation & Policy Optimization"
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
  - "docs/testing/BENCHMARK_PROTOCOL.md"
  - "docs/testing/TEST_STRATEGY.md"
decision_references:
  - "ADR-008"
change_summary: "Research strategy for empirical benchmark gating, error taxonomy, and policy learning."
---

# Research Strategy: Scientific Capability Evaluation & Policy Optimization

## 1. Capability Evaluation Framework

In accordance with [ADR-008](file:///home/thientn204/laris/docs/adr/ADR-008-evaluation-before-capability-claims.md), capability claims must be supported by empirical, reproducible benchmarks.

### The Eight Empirical Capability Dimensions:
1. **Paraphrase & Question Intent Equivalence:** Macro F1 and accuracy on scientific paraphrase sets.
2. **NLI & Contradiction Detection:** Precision/Recall on scientific claim pairs with conflicting findings.
3. **Discourse & Claim Extraction:** Token-level F1 and span exact-match on methods, metrics, and claims.
4. **Heading-Agnostic Limitation Inference:** Sensitivity in detecting implicit caveats in discussion narratives.
5. **Cross-Paper Synthesis Consistency:** Coherence and factual accuracy of comparative condition tables.
6. **Verifiable Gap Discovery Quality:** Expert validation rate of proposed research gaps.
7. **Provenance & Zero Hallucination Rate:** Percentage of generated assertions linked to verified coordinates (Target: 100%).
8. **Hardware Telemetry Compliance:** Peak VRAM $\le 15.0$ GB, zero OOM events, bounded latency.

---

## 2. Policy Learning & Contextual Bandits

For Layer 8 and Layer 9 agent routing and tool selection:
- Initial policy: Deterministic rules and static routing heuristics.
- Intermediate policy: Contextual bandit optimizing tool selection based on task difficulty and historical execution latency.
- Reinforcement learning (RL): Activated **only** after deterministic simulation environments, validated reward signals, and frozen evaluation benchmarks are fully established. Surface fluency is strictly forbidden as a reward signal.
