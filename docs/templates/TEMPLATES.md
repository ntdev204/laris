---
document_id: "DOC-TMPL-ALL-001"
title: "LARIS Document Templates"
document_type: "template"
status: "DRAFT"
version: "0.2.0"
created_at: "2026-10-15"
updated_at: "2026-11-11"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/development/DOCUMENTATION.md"
decision_references: []
change_summary: "Merged the five separate templates into one file; template content unchanged."
---

# LARIS Document Templates

Copy the block you need into a new file and replace the bracketed placeholders. Every document
under `docs/` keeps the front matter shown here, as required by
[DOCUMENTATION.md](../development/DOCUMENTATION.md).

## Standard document template

````markdown
---
document_id: "DOC-TMPL-GEN-001"
title: "Standard Document Template"
document_type: "template"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/development/DOCUMENTATION.md"
decision_references: []
change_summary: "Generic document template conforming to LARIS documentation standards."
---

# [Document Title]

## 1. Executive Summary & Purpose
[Brief statement of document scope, background, and objectives.]

## 2. Core Concepts & Definitions
[Define domain-specific terminology before usage, aligning with docs/GLOSSARY.md.]

## 3. Detailed Technical Content
[Section 1, Section 2, Section 3...]

## 4. Risks, Constraints & Invariants
- [State constraints, invariants, or potential failure modes.]

## 5. Traceability & Source of Truth Links
- [Link to source-of-truth specifications or parent documents.]
````

## Architecture decision record template

````markdown
---
document_id: "DOC-TMPL-ADR-002"
title: "Architecture Decision Record Template"
document_type: "template"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/development/DOCUMENTATION.md"
decision_references: []
change_summary: "Standard template for Architecture Decision Records in templates directory."
---

# ADR-XXX: [Descriptive Decision Title]

## Metadata
- **ADR ID:** ADR-XXX
- **Status:** PROPOSED | ACCEPTED | REJECTED | DEPRECATED | SUPERSEDED
- **Date Proposed:** YYYY-MM-DD
- **Date Decided:** YYYY-MM-DD
- **Decision Owner:** [Team / Role]
- **Target Layers:** [e.g. Layer 1, Layer 9]

## 1. Context and Problem Statement
[Describe the engineering context, forces, limitations, and specific architectural problem that requires a decision. Avoid vague descriptions.]

## 2. Decision
[State the exact architectural choice adopted in direct, active voice. Specify what SHALL be done, what SHALL NOT be done, and the exact scope of the decision.]

## 3. Alternatives Considered
1. **Alternative A:** [Description, strengths, and specific reasons for rejection.]
2. **Alternative B:** [Description, strengths, and specific reasons for rejection.]

## 4. Consequences
### 4.1. Positive Consequences
- [Expected benefit, capability unlocked, or risk reduced.]

### 4.2. Negative Consequences & Trade-offs
- [Increased development complexity, latency overhead, or computational cost.]

### 4.3. Neutral Impact
- [Factors that remain unchanged.]

## 5. Risks and Mitigations
| Identified Risk | Severity | Mitigation Strategy |
| :--- | :--- | :--- |
| [Risk Description] | Low / Med / High | [Concrete mitigation action] |

## 6. Validation and Acceptance Criteria
- [ ] [Quantifiable criterion to verify that the decision is correctly implemented and adheres to constraints.]

## 7. Related Documents
- [Link to SYSTEM_OVERVIEW.md](../architecture/SYSTEM_OVERVIEW.md)
- [Link to Relevant Spec](../specifications/MODULE_CONTRACTS.md)
````

## Specification template

````markdown
---
document_id: "DOC-TMPL-SPEC-001"
title: "Standard Specification Template"
document_type: "template"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/development/DOCUMENTATION.md"
decision_references: []
change_summary: "Specification template for interface contracts, schemas, and protocol definitions."
---

# Specification: [System / Module / Contract Name]

## 1. Scope & Module Identification
- **Module ID:** `MOD-XXX-001`
- **Specification Version:** `0.1.0`
- **Purpose:** [Single sentence purpose statement]
- **Non-Goals:** [Explicit boundaries of what this component will NOT do]

## 2. Interface Contracts
- **Input Schema:** [JSON Schema or typed definition]
- **Output Schema:** [JSON Schema or typed definition]
- **Preconditions:** [State or constraints that must hold before invocation]
- **Postconditions:** [Guarantees provided upon successful return]
- **Error Types & Codes:** [Structured error hierarchy]

## 3. Performance & Resource Bounds
- **Maximum VRAM Allocation:** [e.g. $\le 1.0$ GB]
- **Maximum Host RAM Allocation:** [e.g. $\le 2.0$ GB]
- **Latency Ceiling:** [e.g. $< 50$ ms]

## 4. Invariants & Epistemic Rules
- [Rule 1, Rule 2...]

## 5. Verification & Acceptance Criteria
- [ ] [Testable criterion 1]
- [ ] [Testable criterion 2]
````

## Experiment template

````markdown
---
document_id: "DOC-TMPL-EXP-001"
title: "Standard Research Experiment Plan Template"
document_type: "template"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/development/DOCUMENTATION.md"
  - "docs/testing/BENCHMARK_PROTOCOL.md"
decision_references: []
change_summary: "Standard template for logging scientific experiment plans and hypotheses."
---

# Experiment Plan: [Experiment Title]

## 1. Research Question & Hypothesis
- **Hypothesis:** [Explicit scientific proposition to be tested]
- **Target Capability:** [e.g. Paraphrase detection, NLI contradiction, Gap discovery]
- **Baseline Model / Method:** [Existing standard to beat]

## 2. Experimental Setup
- **Dataset / Version:** [Corpus partition, total tokens/samples, license verification]
- **Model Architecture & Parameters:** [Layers, hidden dim, parameters, activation]
- **Hardware Configuration:** [NVIDIA RTX 5070 Ti 16GB, 32GB RAM, i5-14600KF]
- **Hyperparameters:** [Learning rate, batch size, optimizer, scheduler, seed]

## 3. Evaluation Metrics & Success Criteria
- [Metric 1, target threshold]
- [Metric 2, target threshold]

## 4. Resource & Telemetry Ceilings
- **Max VRAM:** $\le 14.5$ GB
- **Max Training Duration:** [e.g. 24 hours]
````

## Benchmark report template

````markdown
---
document_id: "DOC-TMPL-REP-001"
title: "Standard Benchmark Report Template"
document_type: "template"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/development/DOCUMENTATION.md"
  - "docs/testing/BENCHMARK_PROTOCOL.md"
decision_references:
  - "ADR-008"
change_summary: "Standard template for recording empirical benchmark outcomes."
---

# Benchmark Report: [Suite ID & Run Title]

## 1. Run Metadata
- **Benchmark Suite ID:** `BENCH-XXX-01`
- **Model Checkpoint:** `artifacts/checkpoints/[model_id]`
- **Execution Date:** YYYY-MM-DD
- **Random Seed:** 42
- **Hardware Platform:** NVIDIA GeForce RTX 5070 Ti 16GB, 32GB RAM, i5-14600KF

## 2. Quantitative Results Table
| Metric Name | Baseline Standard | Target Threshold | Measured Score | Pass / Fail |
| :--- | :--- | :--- | :--- | :--- |
| [Metric A] | 0.00 | 0.00 | 0.00 | PASS / FAIL |
| [Metric B] | 0.00 | 0.00 | 0.00 | PASS / FAIL |

## 3. Physical Hardware Telemetry
- **Peak GPU VRAM Allocated:** [e.g. 8.4 GB]
- **Peak Host RAM Used:** [e.g. 14.2 GB]
- **Average Inference Latency:** [e.g. 24 ms/step]
- **Zero OOM Violations:** YES / NO

## 4. Failure Analysis & Taxonomy Errors
- [Summary of error taxonomy classifications, edge cases, and hard negatives.]

## 5. Conclusions & Milestone Impact
- [Assessment against milestone acceptance criteria.]
````
