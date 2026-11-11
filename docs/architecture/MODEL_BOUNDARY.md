---
document_id: "DOC-ARCH-MODEL-BOUNDARY-001"
title: "Model Boundary Contract and Criteria for Resuming the Core Model"
document_type: "architecture"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-11-11"
updated_at: "2026-11-11"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/architecture/AGENT_HARNESS.md"
  - "docs/architecture/BRAIN_AND_VAULT.md"
  - "docs/testing/AGENTIC_SCENARIOS.md"
decision_references:
  - "ADR-008"
  - "ADR-016"
  - "ADR-017"
  - "ADR-018"
change_summary: "States exactly what a core model must provide to plug into the finished harness, how it is checked, and the criteria the owner reviews before model work resumes."
---

# Model Boundary Contract and Criteria for Resuming the Core Model

The harness (loop, tools, policy, brain, vault, server) is built against a *boundary*, not against a
particular model. Any model that satisfies the boundary below can be served; none is trained, fitted or
started by this document or its tests. The core model is **NOT QUALIFIED**.

## 1. The interfaces

| Interface | Shape | Where used |
|---|---|---|
| `ChatProvider.chat(messages, tools) -> AssistantTurn` | messages: OpenAI-style `role`, `content`, `tool_calls`, `tool_call_id`; tools: OpenAI function specs; returns `content` and/or `tool_calls` (`id`, `name`, `arguments` as a dict) | the agent loop, the server (`/v1/chat/completions`, `/v1/laris/chat`) |
| `ChatProvider.stream(...)` | yields `{"type":"text","delta"}`, optional `{"type":"reasoning","delta"}`, then one `{"type":"turn","turn"}` | streaming; reasoning is stored by the server and never shown |
| Backend loading | `package.module:ClassName`, zero-argument constructor, subclass of `ChatProvider` (`laris-server model serve --backend`) | the server |
| Embedder | `callable(list[str]) -> list[list[float]]`, one equal-length vector per text | `/v1/embeddings`, dense retrieval |
| Tool calls | the model may call only the tools it is shown; arguments are validated against the schema; an unknown or disallowed tool returns an error result, never an exception | the loop |
| Plan tool | `update_plan(steps=[{text,status}])`; statuses `pending`, `in_progress`, `done`, `failed`, `skipped` | agentic loop (ADR-017) |
| Brain brief | arrives as a hidden harness message; the model must not quote it; it opens notes with `brain_open(id)` | consult step |
| Usage | the server estimates tokens from characters when the backend gives none | quotas |

Not part of the boundary: how the model is built, its weights, its tokenizer, or any training code.

## 2. What the harness guarantees to the model

Tool results are untrusted data and are redacted; the system prompt and the brain are never shown to the
user; a limit (steps, approvals, allowed tools of a workflow) cannot be widened by the model; reasoning
output is diverted before any response is built.

## 3. How the boundary is checked

`tests/unit/agent/test_model_boundary.py` runs a scripted reference model through every row of the table
(loading, tool calls, plan, brain brief, hidden reasoning, embeddings, rejection of non-providers). A real
model passes the same tests by replacing the reference class; the scenario suite in
`docs/testing/AGENTIC_SCENARIOS.md` then measures planning behaviour, which scripted tests cannot.

## 4. Criteria for resuming the core model (for the owner's review)

The owner decides (task T39); these are the conditions the engineering side proposes.

1. The boundary tests pass with the candidate model in place of the reference class.
2. The model-free suites (`laris-server evaluate suite`) still pass with it served.
3. Formal held-out gates for the capability being claimed exist *before* training and are not changed after
   (ADR-008); reports stay separate from specifications.
4. A training authorisation is written by the owner, names the run, its data and its budget, and is recorded in
   the ledger; no agent starts training, fitting or optimiser-bearing profiling.
5. Weights, datasets and collected fine-tune data stay outside Git.
6. The agentic scenarios are re-run with the real model and the results reported next to the scripted ones,
   with the model's qualification status stated.

Until the owner accepts these, model work stays paused and every answer that depends on the model says it
is not qualified.
