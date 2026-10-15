---
document_id: "DOC-ADR-009"
title: "ADR-009: Embedded Heterogeneous Evidence Graph Storage and Persistence Interface"
document_type: "adr"
status: "ACCEPTED"
version: "1.0.0"
created_at: "2026-10-16"
updated_at: "2026-10-16"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/IDEA.md"
  - "docs/specifications/MODULE_CONTRACTS.md"
  - "docs/architecture/LAYER_ARCHITECTURE.md"
decision_references:
  - "ADR-001"
  - "ADR-004"
  - "ADR-009"
change_summary: "Adopted embedded graph persistence architecture and typed node/edge interface without external database server."
---

# ADR-009: Embedded Heterogeneous Evidence Graph Storage and Persistence Interface

## Metadata
- **ADR ID:** ADR-009
- **Status:** ACCEPTED
- **Date Decided:** 2026-10-16
- **Decision Owner:** LARIS Architecture Team
- **Target Layers:** Layer 5 (Research Knowledge & Evidence Graph), Boundary F (`MOD-GRAPH-001`)

## 1. Context and Problem Statement
Scientific literature analysis in LARIS requires modeling complex, heterogeneous relationships across papers: citations, author networks, experimental methods, evaluated datasets, quantitative results, extracted claims, and acknowledged limitations.

To satisfy the local-first system boundary ([ADR-001](file:///home/thientn204/laris/docs/adr/ADR-001-local-first-system-boundary.md)) and epistemic provenance guarantees ([ADR-004](file:///home/thientn204/laris/docs/adr/ADR-004-evidence-provenance-first-class.md)), the graph storage solution must:
1. Require zero external background database server daemons (e.g. no Neo4j, Dgraph, or Memgraph server processes running as separate services).
2. Maintain strict separation between author-asserted facts and machine-inferred relationships to prevent epistemic conflation.
3. Support low-latency in-memory subgraph traversal and neighborhood queries while providing durable, ACID-compliant on-disk persistence and version migration.
4. Guarantee reproducible serialization and schema evolution across milestone boundaries.

## 2. Decision
1. **Pluggable Persistence Interface:** All graph storage operations SHALL be decoupled behind a stable abstract persistence contract (`BaseGraphPersistenceAdapter`) in Layer 5 (`MOD-GRAPH-001`).
2. **Embedded Graph Storage:** LARIS SHALL NOT require standalone graph database servers. The canonical on-disk persistence backend SHALL be an embedded relational/JSON graph adapter (SQLite-backed edge-list and node store), with an in-memory graph representation for low-latency graph traversals and neighborhood extractions.
3. **Strict Epistemic Edge Invariants:**
   - Every edge in the Evidence Graph SHALL be explicitly typed (`AUTHORED_BY`, `ASSERTS_CLAIM`, `SUPPORTS`, `CONTRADICTS`, `EVALUATES_ON`, `USES_METHOD`, `MEASURES`, `HAS_LIMITATION`, `DERIVED_FROM`).
   - Every edge SHALL include an explicit `is_inferred: bool` flag.
   - Any inferred edge MUST retain `is_inferred = True` and link to an `inference_provenance` coordinate or confidence score. Inferred edges SHALL NEVER overwrite or be conflated with author-asserted edges (`is_inferred = False`).
4. **Schema Versioning & Migration:** Every graph artifact SHALL carry an explicit `schema_version` (e.g. `"1.0.0"`). Version migrations SHALL be orchestrated through a centralized migration registry before loading older schemas.

## 3. Alternatives Considered
1. **Standalone Graph Database Server (e.g. Neo4j, Memgraph, Dgraph):**
   *Rejected because:* Requires daemon installation, separate service life-cycle management, high idle memory consumption (exceeding the strict RAM envelope), and violates the self-contained, zero-configuration local-first boundary.
2. **Pure In-Memory Graph with Ad-Hoc File Dumps (e.g. raw pickle / ad-hoc JSON):**
   *Rejected because:* Lacks transactional guarantees, exhibits poor partial update performance on large graphs, and creates severe migration vulnerabilities across schema versions.
3. **Embedded Relational/JSON Graph Engine (SQLite-backed):**
   *Accepted:* Zero-daemon deployment, single-file portability, ACID transactions, native indexing on node/edge IDs, schema version pragma, and deterministic JSON serialization.

## 4. Consequences
### 4.1. Positive
- 100% self-contained offline execution with zero external background processes.
- Clear contractual boundary between traversal query algorithms and underlying storage.
- Immutable epistemic traceability: users and agents can cleanly distinguish direct author statements from model-inferred hypotheses.
- Seamless schema migration and deterministic test fixtures.

### 4.2. Negative & Trade-offs
- Deep graph traversals (> 5 hops) across millions of nodes require indexed joins or temporary memory graph projection rather than native Cypher graph query acceleration.
- Requires maintaining explicit relational indices on `source_id`, `target_id`, and `edge_type`.

## 5. Risks and Mitigations
| Identified Risk | Severity | Mitigation Strategy |
| :--- | :--- | :--- |
| Conflation of inferred edges with direct author claims | High | Enforce mandatory `is_inferred` flag and raise `InferredEdgeConflationError` if unverified edges lack provenance. |
| Schema mismatch on legacy graph checkpoints | Medium | Enforce semantic versioning header (`schema_version`) and validate migrations via `GraphSchemaMigrationRegistry`. |
| Traversal latency degradation on large graphs | Medium | Cache active neighborhood subgraphs in memory and enforce maximum traversal depth ($N \le 3$). |

## 6. Validation and Acceptance Criteria
- [x] Abstract persistence interface (`BaseGraphPersistenceAdapter`) and in-memory reference adapter defined with 100% test coverage.
- [x] Inferred edges strictly separated from author-asserted edges; conflation raises validation errors.
- [x] Graph serialization and deserialization roundtrip verified with zero data or precision loss.
- [x] No external database daemon or service required for execution.

## 7. Related Documents
- [IDEA.md](file:///home/thientn204/laris/docs/IDEA.md)
- [MODULE_CONTRACTS.md](file:///home/thientn204/laris/docs/specifications/MODULE_CONTRACTS.md)
- [LAYER_ARCHITECTURE.md](file:///home/thientn204/laris/docs/architecture/LAYER_ARCHITECTURE.md)
- [ADR-001: Local-First System Boundary](file:///home/thientn204/laris/docs/adr/ADR-001-local-first-system-boundary.md)
- [ADR-004: Evidence Provenance First-Class](file:///home/thientn204/laris/docs/adr/ADR-004-evidence-provenance-first-class.md)
