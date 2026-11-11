---
document_id: "DOC-ADR-017"
title: "ADR-017: Runtime Layers (Loop, Harness, Prompt) and the Capability Ladder (LLM, RAG, Agent, Agentic)"
document_type: "adr"
status: "ACCEPTED"
version: "1.0.0"
created_at: "2026-11-11"
updated_at: "2026-11-11"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/adr/ADR-016-policy-server-and-thin-client.md"
  - "docs/architecture/AGENT_HARNESS.md"
decision_references:
  - "ADR-016"
change_summary: "Fixes the vocabulary and dependency direction of the runtime layers and sets Agentic as the system's required capability level, with measurable criteria."
---

# ADR-017: Runtime Layers and Capability Ladder

## Metadata
- **ADR ID:** ADR-017
- **Status:** ACCEPTED (owner instruction, 2026-11-11: standardise `loop -> harness -> prompt` and `LLM -> RAG -> Agent -> Agentic`; the system must reach Agentic)

## 1. Runtime layers

| Layer | Code | Owns | Must not |
|-------|------|------|----------|
| Loop | `agent.loop`, `agent.context`, `agent.tools` | The bounded cycle: compact, model call, tool calls, guard, verify, stop | Read policy files or contain prompt text |
| Harness | `harness.*`, `gateway` (server) | Configuration, guards, approval and path policy, workflows, audit, integrity; it runs the loop inside its limits | Be bypassed by a front end |
| Prompt | `harness.prompts` | The text sent to the model for one call, composed by the harness from versioned modules, rules, the user's layers and the brain brief | Import the loop or run tools |

Dependency direction: the loop runs inside the harness; the harness composes the prompt; the prompt layer
knows neither the loop nor the tools. On the wire (ADR-016) the prompt and the harness's policy half live
on the server, the loop and tools on the client.

## 2. Capability ladder

Each rung includes the one before and adds one capability.

| Rung | Adds | In LARIS | Status |
|------|------|----------|--------|
| LLM | Answers from the model's weights | Core model | Paused; NOT QUALIFIED |
| RAG | Grounded answers: retrieval over the user's documents, citations `[source #rank]`, a verifier | `retrieval`, workspace, vault, verifier | Working; BM25 is the trusted channel |
| Agent | Tools and a bounded loop with approval | `agent.loop`, tool registry, skills, workflows | Working |
| Agentic | Pursues a goal across steps without being told each one: plans, tracks progress, reflects and replans, checks completion, remembers and resumes, inside hard limits | Plan (`update_plan`), reflection, completion check, resume and vault memory in the loop (tasks T43-T46); scripted scenarios pass | Implemented at harness level; model NOT QUALIFIED |

## 3. Agentic requirement (the system must achieve it)

The harness must show, on scripted scenarios that need no trained model, all of:

1. **Plan:** for a multi-step goal a visible plan (steps with status) exists before the first tool call.
2. **Track and resume:** the plan and its progress are stored in the session and the project vault; an
   interrupted goal continues after `laris --resume`.
3. **Reflect and replan:** after each tool result the loop checks progress; a failed or empty step triggers a
   bounded replan, never an unbounded retry.
4. **Completion check:** the goal is closed only when its done-criteria hold (workflow output sections,
   citations), otherwise the loop continues or reports what is missing.
5. **Memory:** results worth keeping are written to the vault by domain and recalled in later sessions.
6. **Bounded autonomy:** steps, time, tool calls, approvals, stop conditions and audit hold at every
   step; autonomy never widens a limit.

Reaching Agentic is a statement about the harness. The quality of the plans depends on the model, which
stays NOT QUALIFIED until the owner resumes it; no answer may claim scientific capability that was not
measured.

## 4. Consequences

- Ledger tasks T42 to T46 implement the layer contract and the six criteria; T42 is enforced by a test.
- Terminology in documents and code comments follows the tables above.
