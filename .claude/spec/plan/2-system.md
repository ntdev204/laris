# LARIS — Plan 2: System, server and client (Rust)

Version 2.0.0-draft · 2026-11-13 · Implements [spec.md](../spec.md) sections 5.1, 5.2 and 7.1-7.7; tasks in
[task/2-system.md](../task/2-system.md).

## 1. How this programme works

- The system is built in its layers, **loop → harness → prompt** (phases 28-30). The server climbs the ladder
  **LLM → RAG → Agent → Agentic** (phases 31-34), each rung closed by an end-to-end scenario (SR-S9). The client
  follows once the model is finished (phase 35, after T118).
- Programme 1 has priority: phases 26-34 run while the next programme-1 task waits for the owner (spec section 2).
- One task, one feature branch cut from `main` (`feature/Txx-<slug>`), one session; report each step.
- A task ends with `cargo fmt --check`, `cargo clippy -D warnings`, `cargo test`, `cargo deny check`, the spec check
  and a merge into `main`. No dependency without the owner's approval (T119).
- Generation 2 does not depend on generation 1 (owner decision 2026-11-18). its branch `laris-v1` was removed (2026-11-20); nothing
  from it is reused or kept compatible.
- With the placeholder backend, scenarios prove mechanics only; capability claims wait for a qualified model.

## 2. Phases

### Phase 26 — Rust foundations
Goal: approved toolchain, recorded decisions, a workspace with CI.
Tasks: T119, T120, T121, T122
Exit criteria:
- Toolchain and crates approved; ADR-021 records D27-D43; `AGENTS.md` updated with the owner's approval.
- Empty workspace green in CI (fmt, clippy, test, deny, spec, no-training guard); threat model written.

### Phase 27 — Protocol and shared libraries
Goal: one schema source and the libraries both binaries use.
Tasks: T123, T124, T125, T126, T127
Exit criteria:
- The committed SSE fixtures and Ink scenarios validate against the Rust types.
- The fixture vault yields the recorded index; writer property tests pass.

### Phase 28 — System: loop
Goal: the state machine runs headless with a scripted model and records everything.
Tasks: T128, T129, T130, T131
Exit criteria:
- Replay from the event log is byte-identical; translated Agentic scenarios pass with a scripted model and decider.

### Phase 29 — System: harness
Goal: tools, policy, sandbox, evidence and learning data around the loop.
Tasks: T132, T133, T134, T135, T214, T136, T137, T138
Exit criteria:
- Tool, permission, hook, sandbox (three platforms; Windows and macOS runs are T214), redaction, evidence and learning-data tests pass.

### Phase 30 — System: prompt
Goal: the prompt layer and the model-free evaluation runner.
Tasks: T139, T140
Exit criteria:
- Layer contract test (loop → harness → prompt) passes; pinned items survive compaction; the evaluation runner replays
  golden and Agentic scenarios in one command.

### Phase 31 — Server: LLM
Goal: `laris-server` serves chat through the model service with keys, quotas and storage.
Tasks: T141, T142, T143, T144
Exit criteria:
- Status-code, quota and storage tests pass; a fresh database gets every migration; the LLM-rung scenario passes.

### Phase 32 — Server: RAG
Goal: grounded answers from workspace retrieval and the system brain.
Tasks: T145, T146, T215, T217, T147, T148
Exit criteria:
- Retrieval matches the recorded expectations; confidentiality suite passes; brain navigation within budget; the RAG-rung
  scenario passes with the evidence gate.

### Phase 33 — Server: Agent
Goal: local and remote tools end to end.
Tasks: T149, T150, T151
Exit criteria:
- Scientific remote tools reproduce the extraction results; traces hold no content; the Agent-rung scenario passes.

### Phase 34 — Server: Agentic
Goal: the full ladder on the deployed stack.
Tasks: T152, T153, T154
Exit criteria:
- The Agentic-rung suite passes against the compose stack; deployment smoke test passes; security suite and
  performance budgets pass.

### Phase 35 — Client (after the model is finished)
Goal: `laris` works like Claude Code and installs in one command.
Tasks: T155, T156, T157, T158, T159
Exit criteria:
- Golden scenarios pass through the interface; owner screenshot review; one-command install per platform.

### Phase 36 — Acceptance and release 1.0.0
Goal: the Rust system replaces the Python one.
Tasks: T160, T161
Exit criteria:
- Acceptance checklist complete; release 1.0.0 merged with the owner's authorisation.

### Phase 45 — One-command server and zero-setup client
Goal: the owner starts and stops the server with one command and a user enters only a key.
Tasks: T236
Exit criteria:
- `docker/laris.sh` runs the stack; the client release carries its server address; release 1.0.1 is published.

### Phase 46 — Full-screen terminal interface
Goal: the client fills the terminal like `vim` and keeps the history of a session.
Tasks: T237
Exit criteria:
- Full-screen layout, scrolling and restore on exit are tested in an emulator; a resumed session shows its history; the owner approves on Windows.

### Phase 47 — Request pipeline in the server
Goal: a request is checked, filtered, grounded and decided in the server before the model is asked.
Tasks: T238, T239, T240, T241, T242, T243
Exit criteria:
- ADR-025 accepted; the server runs the Prefilter, retrieval, brain decider and evidence gate; the client shows the stages; the smoke test and the cognitive evaluation pass through the server. The model stays NOT QUALIFIED.

### Phase 48 — Client fixes found in use
Goal: what the owner meets in daily use of the client is fixed and released.
Tasks: T244
Exit criteria:
- The fix is released and the owner confirms it on Windows.

### Phase 49 — The Laris model family
Goal: the client shows the current model, and the user can use Laris Optimus (everyday, no thinking) or Laris Megatron (strongest, thinking, deep reasoning).
Tasks: T245, T246, T247, T248
Exit criteria:
- ADR-026 accepted; the server serves the named models with per-role access and a VRAM budget; the client shows the model and role in its banner and switches with `/model`; both models are measured and reported as system measurements. The names are not qualifications.

### Phase 50 — Auto permission mode
Goal: the client works without approval prompts by default, and still asks before clearly destructive commands.
Tasks: T249
Exit criteria:
- `auto` exists in every place a mode is named, is the default, and is covered by mode tests; the guard list is configuration.


### Phase 51 — Client interface refresh
Goal: the client looks and works like the familiar terminal assistants: a plain input box, a quiet status line, no internal stages, and the usual informational slash commands.
Tasks: T250
Exit criteria:
- The input box is two rules and a `>` prompt; the banner is two lines; the status line shows model, context and tokens left; pipeline stages are hidden unless one fails; `/quit` is gone; `/usage`, `/context`, `/model`, `/config` and `/export` exist and are covered by tests; the status line's context figure comes from real usage.

### Phase 52 — Automatic update
Goal: the client keeps itself current without the user doing anything, and says so when a restart will apply it.
Tasks: T251
Exit criteria:
- The interface checks the release address in the background, installs a newer signed release over the program, and shows a notice above the input box at the right until `/restart` applies it; a bad signature, list or archive is never installed; covered by tests.

### Phase 53 — Informational panels like the familiar assistants
Goal: `/usage`, `/context` and `/config` read like the familiar terminal assistants: bars, a context grid and aligned lists.
Tasks: T252
Exit criteria:
- The three commands show their panels as described in T252; tests and the Rust task checks pass.

### Phase 54 — MCP tools and web search
Goal: the client can reach the web through MCP servers, confined and asked about like every other tool.
Tasks: T253, T254, T255
Exit criteria:
- SR-H16 and SR-H17 hold: the MCP bridge (no default servers), the web tools and the clock, `/mcp`, the `*` rule form and the guide are built and tested; the real network is tried by the owner on a networked machine.
