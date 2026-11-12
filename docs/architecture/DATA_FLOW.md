---
document_id: "DOC-ARCH-FLOW-001"
title: "LARIS End-to-End Data Flow and Pipeline Architecture"
document_type: "architecture"
status: "DRAFT"
version: "0.2.0"
created_at: "2026-10-15"
updated_at: "2026-11-13"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/architecture/SYSTEM_OVERVIEW.md"
  - "docs/architecture/SYSTEM_OVERVIEW.md"
  - "docs/architecture/LAYER_ARCHITECTURE.md"
  - "docs/specifications/DATA_SCHEMAS.md"
  - "docs/adr/ADR-019-three-blocks-two-protocols-two-sql-engines.md"
decision_references:
  - "ADR-003"
  - "ADR-004"
  - "ADR-005"
  - "ADR-015"
  - "ADR-018"
  - "ADR-019"
change_summary: "Adds pipeline 0, the flow of one chat turn through client, proxy, API, model and back (release 2.0), and the embedding and tool-loop paths; pipelines 1 to 4 are unchanged."
---

# LARIS End-to-End Data Flow and Pipeline Architecture

This document maps the flow of data through LARIS, tracing data transformations, intermediate schemas, validation checkpoints, and failure recovery pathways across the operational pipelines. Pipeline 0 is the runtime path of the 2.0 system (a chat turn); pipelines 1 to 4 are the research data pipelines.

---

## 0. Pipeline 0: One Chat Turn (release 2.0)

The runtime path from a typed message to a stored trace. The blocks and protocols are described in
[SYSTEM_OVERVIEW](SYSTEM_OVERVIEW.md) section 1b; the loop that wraps it is in
[AGENT_HARNESS](AGENT_HARNESS.md). The foundation model is not qualified, so this flow guarantees how
a turn is governed, not how good the answer is.

```mermaid
sequenceDiagram
    participant FE as Front end
    participant EN as Engine (client)
    participant CD as Caddy
    participant API as API (server)
    participant MD as Model service
    participant PG as PostgreSQL
    FE->>EN: user_message (E1)
    EN->>EN: compose the user's layers, tool schemas, skills index, memory
    EN->>CD: POST /v1/laris/chat (P1, key, X-Laris-Protocol)
    CD->>API: forwarded, real peer address set
    API->>API: trusted-proxy address, key check, role, body validation
    API->>PG: reserve estimated tokens (quota)
    API->>API: gateway composes policy prompt, consults the brain (brain budget lock)
    API->>MD: chat completion stream (P2, bounded concurrency)
    MD->>MD: GPU queue stages the needed model, generates
    MD-->>API: token stream (text, reasoning, tool calls)
    API->>API: leak and secret guard, reasoning diverted, brain tools run here
    API-->>EN: SSE text and the client's own tool calls
    API->>PG: settle quota and store the trace (finally)
    EN->>EN: permission check, hooks, run the tool locally
    EN->>CD: next request with the tool result
    EN-->>FE: text, tool_call, tool_result, done (E1)
```

| Step | Where | Rule |
| :--- | :--- | :--- |
| 1. Compose | client | Only what belongs to the user leaves the machine: conversation, tool schemas, the user's instruction files, skills index and memory. Keys typed into a message are masked before storage |
| 2. Send | client to Caddy | HTTPS; the protocol header is checked by the server (426 on mismatch); a stream that fails is reported as an `error` event |
| 3. Admit | Caddy, API | Timeouts and the 32 MB limit at the edge; the real address comes from a trusted proxy only; the key is checked (401), the role must allow the route (403), the body is validated (4xx, never 500) and the estimated tokens are reserved (429 when the quota is used up) |
| 4. Compose policy | API gateway | The gateway adds the system prompt, rules, workflows and a short brain brief. Nothing in `.laris/` is ever sent back to the client; the brain lock covers the brain budget only |
| 5. Infer | API to model (P2) | Bounded concurrency; chat and embeddings share one GPU queue, which loads the model the job needs and evicts the least recently used idle model when the budget is exceeded |
| 6. Guard | API gateway | The stream passes the leak detector and secret redaction; reasoning is diverted and kept for the operator only (ADR-018); a leak is replaced by the configured refusal |
| 7. Return | API to client | SSE: text and the client's own tool calls; brain tool calls are run on the server and are not returned |
| 8. Settle | API, `finally` | The reservation is settled with real use (or released) and the trace stored, also when the client drops the stream |
| 9. Act | client | The engine applies permission modes and rules, runs `PreToolUse` hooks, runs the tool in the project folder (installs only in the sandbox), runs `PostToolUse` hooks, and sends the result in the next request. A turn ends at the step ceiling, a repeated call, the time budget, an interrupt or a final answer |

**Embeddings.** Dense search never runs a model on the client. The workspace sends passages to
`POST /v1/laris/embed`; the API forwards them to the model service over P2 (`/v1/embeddings`), and the
client caches the vectors in its SQLite `embeddings` table. Without a configured server only BM25 search works.

**Failure paths.** A model failure before the first byte is an HTTP error; after the stream starts it is an
`error` SSE event followed by the end marker. A client interrupt (Esc) ends the local turn and leaves the saved
conversation valid: every tool call has a result. The server settles quota in every case.

**What is stored where.** Conversation, uploads, tool results, learning data and the vault index stay in the
user's SQLite space and folders. The server keeps only `keys`, `usage` (token counts per key and month),
`traces` (including diverted reasoning, for the operator) and the daily summary; usage rows are dropped after
`serving.usage_retention_days` (90) and traces after `serving.trace_retention_days` (30).

---

## 1. Pipeline 1: Document Ingestion and Knowledge Construction

The Ingestion Pipeline transforms raw, multi-format scientific literature into structured, queryable knowledge graph representations anchored to source coordinates.

```mermaid
sequenceDiagram
    autonumber
    participant Raw as Raw Document (PDF/HTML/TXT)
    participant L0 as Layer 0: Corpus Foundation
    participant L4 as Layer 4: Document Intelligence
    participant L1 as Layer 1: Language Foundation
    participant L2 as Layer 2: Semantic Intelligence
    participant L3 as Layer 3: Scientific NLP
    participant L5 as Layer 5: Evidence Graph

    Raw->>L0: Submit raw document file
    L0->>L0: Audit license, sanitize Unicode, compute SHA-256
    L0->>L4: Validated document buffer
    L4->>L4: Parse layout, reconstruct reading order, map coordinates
    L4->>L1: Emit canonical DocumentTree
    L1->>L1: Tokenize sentences, extract syntactic dependency trees
    L1->>L2: Tokens & Sentence embeddings
    L2->>L2: Parse coreference chains & discourse connectives
    L2->>L3: Discourse-annotated sentence graph
    L3->>L3: Extract claims, methods, results, limitations, assumptions
    L3->>L5: Structured Entities (Claims, Evidence, Methods)
    L5->>L5: Update Knowledge Graph with verified provenance links
```

### Intermediate Data Formats in Pipeline 1:
- **L0 $\rightarrow$ L4:** `CleanCorpusItem` (raw text, license tag, document SHA-256).
- **L4 $\rightarrow$ L1:** `DocumentTree` (hierarchical sections, paragraphs, sentences, exact bounding boxes).
- **L1 $\rightarrow$ L2:** `TokenizedSentence` with dense vector embeddings and dependency tags.
- **L2 $\rightarrow$ L3:** `DiscourseRelationSpan` with NLI and coreference links.
- **L3 $\rightarrow$ L5:** `ClaimRecord`, `EvidenceCoordinate`, `LimitationRecord`, `MethodRecord`.

---

## 2. Pipeline 2: Research Query & Hierarchical Evidence Retrieval

When a user submits a complex research question, Pipeline 2 decomposes the query and executes depth-adaptive retrieval across textual, semantic, and graph indexes.

```mermaid
flowchart TD
    UserQuery["User Research Question"] --> L11["Layer 11: UI Ingestion"]
    L11 --> L8["Layer 8: Supervisor / Query Planner"]
    L8 --> Subqueries["Atomic Research Intents & Sub-questions"]
    
    Subqueries --> L6["Layer 6: Hybrid Hierarchical RAG"]
    
    subgraph MultiChannel["Multi-Channel Retrieval Engine"]
        L6 --> BM25["Lexical Search (BM25)"]
        L6 --> Dense["Dense Semantic Retrieval (L1 Encoders)"]
        L6 --> GraphQ["Graph Traversal (L5 Evidence Graph)"]
    end
    
    BM25 --> Reranker["Multi-Stage Reranker"]
    Dense --> Reranker
    GraphQ --> Reranker
    
    Reranker --> DepthCheck{"Evidence Sufficient & Consistent?"}
    DepthCheck -- "No (Uncertainty High)" --> Expand["Expand Retrieval: Sentence -> Paragraph -> Document"]
    Expand --> MultiChannel
    DepthCheck -- "Yes" --> EvidencePkg["Calibrated Evidence Package with Coordinates"]
    EvidencePkg --> L7["Layer 7: Research Reasoning Engine"]
```

---

## 3. Pipeline 3: Cross-Paper Synthesis & Research Gap Discovery

Pipeline 3 executes scientific reasoning over retrieved evidence packages to compare methodologies, detect empirical contradictions, and discover verifiable research gaps.

```mermaid
flowchart TD
    EP["Calibrated Evidence Packages"] --> S1["1. Align Studies by Method & Experimental Setup"]
    S1 --> S2["2. Build Comparative Outcome Matrix"]
    S2 --> S3["3. Categorize Epistemic Status (Facts vs Speculations)"]
    S3 --> S4["4. Identify Inconsistencies & Latent Boundary Limitations"]
    
    S4 --> G1["5. Generate Candidate Gaps (12-Class Taxonomy)"]
    G1 --> G2["6. Adversarial Counter-Evidence Query (Layer 6 Search)"]
    
    G2 --> G3{"Counter-Evidence Found in Corpus?"}
    G3 -- "Yes (Already Solved)" --> Reject["Discard Candidate Gap / Record Known Finding"]
    G3 -- "No (Genuine Unexplored Area)" --> Score["7. Compute Calibrated Gap Score (Novelty, Grounding, Feasibility)"]
    
    Score --> Plan["8. Formulate Concrete Empirical Validation Plan"]
    Plan --> L8Out["Layer 8: Critical Reviewer Verification"]
```

---

## 4. Pipeline 4: Synthesis, Verification, and Report Generation

Pipeline 4 converts reasoned conclusions into a structured research report with zero tolerance for unreferenced assertions.

```mermaid
flowchart TD
    L8Out["Verified Synthesis & Ranked Gaps"] --> L8Comp["Layer 8: Report Composer Agent"]
    L8Comp --> DraftReport["Draft Structured Research Report"]
    
    DraftReport --> L8Crit["Layer 8: Critical Reviewer / Adversarial Verifier"]
    
    subgraph VerificationGate["Automated Quality & Provenance Gate"]
        L8Crit --> Chk1["Verify 100% Claims have valid EvidenceCoordinate"]
        L8Crit --> Chk2["Verify no Epistemic Overreach (Correlation != Causation)"]
        L8Crit --> Chk3["Verify Hardware Telemetry within Limits"]
    end
    
    Chk1 & Chk2 & Chk3 --> GatePass{"All Verification Checks Pass?"}
    GatePass -- "Fail" --> Remediation["Remediate: Flag missing evidence / Downgrade claim status"]
    Remediation --> DraftReport
    
    GatePass -- "Pass" --> FinalReport["Official Structured Research Report"]
    FinalReport --> L11UI["Layer 11: Interactive User Interface"]
```
