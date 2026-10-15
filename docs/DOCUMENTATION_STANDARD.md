---
document_id: "DOC-GOV-STD-001"
title: "LARIS Documentation Standard & Metadata Specification"
document_type: "specification"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/IDEA.md"
  - "docs/DOCUMENT_LIFECYCLE.md"
  - "docs/GLOSSARY.md"
decision_references:
  - "ADR-007"
change_summary: "Initial standard for document metadata, authoring rules, and source-of-truth governance."
---

# LARIS Documentation Standard & Metadata Specification

## 1. Overview & Purpose

The LARIS project enforces strict documentation discipline to ensure that architectural integrity, empirical provenance, and engineering standards are maintained as the system scales. This document specifies the required metadata schema, writing guidelines, terminology consistency rules, and source-of-truth policies for all technical documentation in the LARIS repository.

## 2. Required Document Metadata Schema

Every technical document in the repository MUST commence with a standardized YAML front matter block adhering to the schema below:

```yaml
---
document_id: "DOC-<TYPE>-<ID>"
title: "<Comprehensive Document Title>"
document_type: "idea | architecture | specification | adr | plan | research | test | report"
status: "DRAFT | IN_REVIEW | APPROVED | FROZEN | DEPRECATED"
version: "X.Y.Z"
created_at: "YYYY-MM-DD"
updated_at: "YYYY-MM-DD"
owner: "<Role or Team, e.g. LARIS Architecture Team>"
reviewers:
  - "<Reviewer 1>"
source_of_truth: true
related_documents:
  - "docs/path/to/related_document.md"
decision_references:
  - "ADR-001"
change_summary: "<Concise summary of the latest modification>"
---
```

### 2.1. Metadata Field Definitions

| Field Name | Type | Allowed Values / Format | Description |
| :--- | :--- | :--- | :--- |
| `document_id` | String | `DOC-[A-Z0-9]+(-[A-Z0-9]+)*` | Globally unique identifier across all repository documents. |
| `title` | String | UTF-8 Text | Canonical human-readable document title. |
| `document_type` | Enum | `idea`, `architecture`, `specification`, `adr`, `plan`, `research`, `test`, `report` | Functional classification of the document. |
| `status` | Enum | `DRAFT`, `IN_REVIEW`, `APPROVED`, `FROZEN`, `DEPRECATED` | Lifecycle state as defined in `docs/DOCUMENT_LIFECYCLE.md`. |
| `version` | String | Semantic Versioning `MAJOR.MINOR.PATCH` | Document content revision level. |
| `created_at` | String | ISO 8601 Date (`YYYY-MM-DD`) | Date of document creation. |
| `updated_at` | String | ISO 8601 Date (`YYYY-MM-DD`) | Date of most recent revision. |
| `owner` | String | Role, Team, or Author name | Accountable entity for document maintenance. |
| `reviewers` | List | Array of names/roles | Designated reviewers who vetted the document. |
| `source_of_truth` | Boolean | `true` or `false` | Indicates whether this document is the primary authority for its scope. |
| `related_documents`| List | Array of repository-relative paths | Key associated documents and upstream/downstream specifications. |
| `decision_references`| List | Array of ADR IDs (`ADR-XXX`) | Explicit architectural decisions governing this document. |
| `change_summary` | String | Text | Summary of changes introduced in the current version. |

## 3. Document Content Standards

### 3.1. Normative Language (RFC 2119)
Authors MUST adhere strictly to standard requirement levels:
- **MUST / SHALL:** Absolute requirement. Non-negotiable for system correctness or policy compliance.
- **MUST NOT / SHALL NOT:** Absolute prohibition.
- **SHOULD / RECOMMENDED:** Best practice or strong recommendation. Valid reasons may exist in particular circumstances to ignore, but the full implications must be understood and documented.
- **SHOULD NOT / NOT RECOMMENDED:** Strongly discouraged practice.
- **MAY / OPTIONAL:** Permissible alternative without negative architectural impact.

### 3.2. Categorical Separation of Epistemic Statements
To prevent ambiguity and unsubstantiated claims, documents MUST clearly separate:
1. **Facts:** Objectively verifiable observations, empirical measurements, or physical hardware constraints.
2. **Decisions:** Accepted, authorized architectural commitments (must reference an accepted ADR).
3. **Assumptions:** Working premises accepted temporarily without full empirical proof, explicitly flagged.
4. **Hypotheses:** Testable propositions that require future experimental validation before acceptance.
5. **Open Questions:** Unresolved issues, trade-offs, or unknowns requiring investigation or stakeholder approval.

### 3.3. Ban on Empty Marketing Buzzwords
Technical documentation MUST NOT use vacuous qualifiers such as "ultra-fast", "highly accurate", "optimal", "super-intelligent", or "seamless" unless accompanied by:
- A concrete mathematical definition or metric.
- An explicit target baseline or comparative threshold.
- The benchmark protocol used to measure it.

### 3.4. Terminology Consistency
All technical terms, entity names, and architectural concepts MUST match their canonical definitions in [docs/GLOSSARY.md](file:///home/thientn204/laris/docs/GLOSSARY.md). Inventing ad-hoc synonyms for established concepts is strictly prohibited.

### 3.5. Evidence and Metric Sourcing
Any numerical figure (VRAM capacity, latency, accuracy percentage, parameter count) MUST:
- Cite its empirical measurement source (e.g. benchmark report or hardware spec sheet), OR
- Be explicitly labeled as `[ESTIMATE]` or `[THEORETICAL TARGET]`.

### 3.6. Examples vs. Ground Truth
Illustrative code blocks, sample queries, and mock outputs MUST be explicitly prefixed with `[EXAMPLE]` to prevent developers or agents from misconstruing mock data as validated test baselines.

---

## 4. Document Types and Canonical Scopes

| Document Type | Primary Scope and Intent |
| :--- | :--- |
| **`idea`** | High-level vision, problem statement, philosophical tenets, system boundaries, and foundational constraints. Governed directly by project leadership. |
| **`architecture`** | System topology, structural layers, data flows, routing mechanics, storage hierarchy, and cross-cutting concerns. |
| **`specification`** | Formal, testable interface contracts: input/output schemas, error hierarchies, preconditions, postconditions, and invariant rules. |
| **`adr`** | Architectural Decision Records: contextual analysis, alternatives evaluated, trade-offs, and consequences of a single engineering choice. |
| **`plan`** | Work breakdowns, milestones, dependencies, resource allocations, entry/exit criteria, and risk mitigation schedules. |
| **`research`** | Theoretical foundations, algorithm evaluations, scientific literature reviews, model formulation, and experimental research notes. |
| **`test`** | Benchmark protocols, test harnesses, evaluation metrics, regression criteria, and empirical verification procedures. |
| **`report`** | Structured findings, benchmark outcomes, system status audits, and experimental results synthesized for human or agent consumption. |

---

## 5. Source-of-Truth Hierarchy & Conflict Resolution

### 5.1. Hierarchy of Authority
When discrepancies arise between documents, authority is resolved in the following descending order:
1. **Frozen Architectural Decisions (Accepted ADRs):** The supreme technical authority for approved design choices.
2. **System Vision (`docs/IDEA.md`):** The definitive authority for system scope, principles, and strategic goals.
3. **Formal Module Specifications (`docs/specifications/`):** The authoritative definition of runtime contracts and schemas.
4. **Architecture Documents (`docs/architecture/`):** Authoritative for overall topology and data flows.
5. **Research & Testing Specifications (`docs/research/`, `docs/testing/`):** Authoritative for experimental methods and benchmarks.
6. **Plans and Roadmaps (`docs/plans/`):** Operational scheduling; never overrides architectural specifications.
7. **Readmes and Summaries (`README.md`, `docs/README.md`):** Convenience indexes only. They MUST NOT introduce independent architectural specifications.

### 5.2. Conflict Resolution Workflow
- Under no circumstance should a developer or agent arbitrarily select the newer file when a conflict exists.
- Any conflicting statements MUST be logged in [docs/OPEN_QUESTIONS.md](file:///home/thientn204/laris/docs/OPEN_QUESTIONS.md) as a formal defect or open question.
- Resolution requires either an ADR amendment, a formal change request, or stakeholder consensus before code or documentation modifications proceed.

### 5.3. Prohibition of Duplication
Do not copy large sections of text between documents. If a document depends on a definition, architecture diagram, or contract established elsewhere, it MUST provide a Markdown link to the canonical source-of-truth document.
