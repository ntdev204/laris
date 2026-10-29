---
document_id: "DOC-ADR-006"
title: "ADR-006: Modular Specialist Architecture with Learned Task Routing"
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
  - "docs/architecture/MODEL_ROUTING.md"
  - "docs/specifications/ORCHESTRATION_SPECIFICATION.md"
decision_references:
  - "ADR-006"
change_summary: "Approved modular specialist architecture and dynamic task routing model."
---

# ADR-006: Modular Specialist Architecture with Learned Task Routing

## Metadata
- **ADR ID:** ADR-006
- **Status:** ACCEPTED
- **Date Decided:** 2026-10-15
- **Decision Owner:** LARIS Architecture Team
- **Target Layers:** Layer 8 (Agent Orchestration), Layer 9 (Adaptive Model Execution)

## 1. Context and Problem Statement
Scientific intelligence spans widely divergent capabilities: parsing LaTeX equations, classifying grammatical discourse connectives, resolving coreference, verifying numerical experimental metrics, querying knowledge graphs, evaluating methodological validity, and formatting research reports.

Attempting to force all these heterogeneous functions into a single monolithic model results in negative task interference, excessive compute consumption, catastrophic forgetting during domain updates, and complete lack of modular debuggability.

## 2. Decision
1. **Modular Specialist Paradigm:** LARIS SHALL be architected as a network of decoupled, specialized components ("Specialists") coordinated by an intelligent Task Router and Agent Orchestrator.
2. **Specialist Diversity:** Specialists MAY take different architectural forms:
   - Compact neural encoders (e.g. 50M–150M parameter sentence/discourse models).
   - Dedicated classification heads (e.g. 3-way NLI, 12-class gap classifier).
   - Symbolic and rule-based engines (e.g. unit normalizers, schema validators).
   - Deterministic graph algorithms (e.g. shortest-path contradiction search).
3. **Multi-Agent Teaming:** Layer 8 SHALL maintain distinct agent roles (`Supervisor`, `Query Planner`, `Language Analysis Agent`, `Document Analysis Agent`, `Evidence Retrieval Agent`, `Scientific Claim Agent`, `Cross-Paper Synthesis Agent`, `Gap Discovery Agent`, `Critical Reviewer`, `Report Composer`).
4. **Conditional Execution:** No workflow is required to execute all agents or all models. The Task Router SHALL dynamically construct minimal execution Directed Acyclic Graphs (DAGs) tailored to the specific query, uncertainty level, and available resource budget.
5. **Standardized Contracts:** Every specialist and agent MUST implement standard interface contracts defining input schemas, output schemas, pre/postconditions, error handling, and performance metrics as specified in [docs/specifications/MODULE_CONTRACTS.md](../specifications/MODULE_CONTRACTS.md).

## 3. Alternatives Considered
1. **Single Monolithic Generalist Model:**
   *Rejected because:* Unmanageable VRAM footprint, impossible to upgrade one capability without retrained interference across all capabilities.
2. **Static Fixed Pipeline (Linear Cascade):**
   *Rejected because:* Forces simple queries through all pipeline stages, wasting compute and multiplying latency needlessly.

## 4. Consequences
### 4.1. Positive
- Independent upgradeability: any specialist model or skill can be retrained and validated without touching others.
- Extreme computational efficiency: simple queries terminate early with lightweight modules.
- High interpretability: individual agent reasoning steps and specialist outputs are isolated and inspectable.

### 4.2. Negative & Trade-offs
- Orchestration complexity: requires robust state management, error handling, and retry logic.
- Potential inter-agent communication latency and serialization overhead.

## 5. Risks and Mitigations
| Risk | Severity | Mitigation Strategy |
| :--- | :--- | :--- |
| Cascade failure where an early agent provides erroneous input to downstream specialists | High | Implement the `Critical Reviewer / Verifier` agent and deterministic schema validation gates between pipeline steps. |
| Over-fragmentation of modules leading to orchestration bloat | Medium | Maintain coarse-grained layer boundaries and enforce strict contract reviews. |

## 6. Validation and Acceptance Criteria
- [ ] New specialist models or skills can be integrated into the execution engine via configuration without altering core router code.
- [ ] Task router selects appropriate execution subgraphs based on query complexity benchmarks.
