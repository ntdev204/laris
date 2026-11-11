---
document_id: "DOC-DEV-CLI-001"
title: "LARIS Command-Line Interface Reference"
document_type: "specification"
status: "APPROVED"
version: "1.1.0"
created_at: "2026-10-29"
updated_at: "2026-11-10"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md"
  - "docs/specifications/DATASET_SPECIFICATION.md"
  - "docs/adr/ADR-013-functional-package-layout-and-cli.md"
decision_references:
  - "ADR-013"
change_summary: "Adds offline formal readiness, links the owner-only runbook and documents citation-ID verification versus source-backed extractive certification."
---

# LARIS Command-Line Interface Reference

The `laris` entry point (`src/cli/main.py`) exposes one module per command under `src/cli/commands/`. Each module defines `add_arguments(parser)` and `run(args)`. Scripts under `scripts/` are thin wrappers over the same functions. Run `laris <group> <command> --help` for the full option list.

## Commands

| Command | Purpose | Authorization |
| :--- | :--- | :--- |
| `laris data acquire [--only IDS] [--cc100-max-docs N]` | Download and verify datasets; `--only` merges into the existing manifest. Resumable. | none |
| `laris data check [--verify-sha256]` | Verify manifest files, per-task train/val/test coverage and `sentencepiece` before any training step. Exit 0 ready, 1 not ready. | none |
| `laris data partition [--datasets ...] [--num-workers N] [--include-unreviewed-licenses]` | Leakage-safe train/val/test partitioning. Datasets with `NEEDS_LICENSE_REVIEW` are skipped by default. A subset run merges into the existing manifest by `dataset_id`. | none |
| `laris train tokenizer [--extract-only] [--authorized]` | Extract train-only text and fit the SentencePiece 32k BPE tokenizer. | `--authorized` |
| `laris train language-encoder --model-size {compact,large} [--profile-only] --tokenizer-model FILE` | `--profile-only` measures real GPU memory on real tokenized train batches (forward only; with training authorized, backward plus a real optimizer step on a discarded model). Otherwise trains, validates, checkpoints and evaluates the encoder. | training needs `--authorized` and `LARIS_TRAINING_AUTHORIZED=1` |
| `laris evaluate language-encoder --checkpoint DIR --tokenizer-model FILE [--split val\|test]` | Score a checkpoint against baselines and thresholds. Exit codes: 0 passed, 1 below threshold, 2 usage or integrity error. | none |
| `laris evaluate readiness --reports REPORT...` | Offline formal foundation audit; requires matching test evidence and protocols. No model loaded. Exit 0 qualified, 1 not qualified, 2 invalid input. | none |
| `laris evaluate calibrate --reports VAL_REPORT...` | Ratchet `configs/evaluation/language_encoder.yaml` up from passing `val` reports; never lowers, refuses `test` reports. | none |
| `laris infer {nli,...} --checkpoint DIR --tokenizer-model FILE` | Run a single prediction from a checkpoint. | none |

## Owner training and evaluation

The [owner runbook](../training/OWNER_RUNBOOK.md) is the execution reference.
Agents must not execute training, tokenizer fitting, backward/optimizer steps or
optimizer-bearing profiling/tests under the current instruction. `--profile-only`
can run real optimizer steps when `LARIS_TRAINING_AUTHORIZED=1`; its name alone
is not a no-training guarantee.

Baseline-relative `evaluate language-encoder` results do not qualify model 01.
`evaluate readiness` reads existing report files against
`configs/evaluation/foundation.yaml` without running a model. Missing official
metrics, incompatible QA protocols, mixed artifact identities or validation-only
reports block qualification. Model 02 remains unimplemented and must follow the
foundation exit gate.

Training progress and checkpoints remain under
`artifacts/checkpoints/language_encoder/<run-id>/{best,last}`. Resuming requires
matching recorded settings and does not restore the exact streaming data position.

## Report verification scope

`EvidenceGate` checks registered assertion citation IDs only. Its `verification_scope`
metadata is `citation_ids_only`; a passing coverage ratio is not evidence of source
integrity or entailment.

For source-backed extractive reports, use `SourceEvidenceGate(source_documents)`
with `StructuredReportGenerator(evidence_gate=gate)`. Supply canonical UTF-8 source
texts keyed by document ID, and corpus hashes computed from those texts. Every
assertion must equal its cited excerpt; each section's Markdown must equal its
assertion statements joined by blank lines. Empty sections are allowed, but reports
without assertions are rejected. Sources, hashes, coordinate IDs and character spans
are checked. Synthesis and paraphrases remain uncertified: this gate does not infer
semantic support or establish research-gap novelty.

## Local application (`laris app`)

An end-to-end local workflow that needs no extra dependency and never trains or fits.

```bash
laris app ingest path/to/docs data/raw/scifact/corpus__corpus-00000-of-00001.parquet
laris app search --query "..."            # BM25, works without a model
laris app index  --checkpoint <run>/best --tokenizer-model <model>   # dense embeddings
laris app ask    --checkpoint <run>/best --tokenizer-model <model> --query "..."
laris app serve  --checkpoint <run>/best --tokenizer-model <model>   # web UI on 127.0.0.1:8765
```

Accepted inputs are txt, md, pdf (needs `pypdf`), and BEIR corpus `.jsonl` or `.parquet`. The
workspace (`artifacts/app/workspace` by default) holds `chunks.jsonl` and, after `index`,
`embeddings.npy`; adding a document invalidates the dense index. The server binds to localhost,
rejects non-JSON POSTs and exposes `/api/status`, `/api/ingest`, `/api/search`, `/api/answer` and
`/api/index`. Until the foundation model is qualified the UI shows a research-preview notice;
BM25 is the reliable channel and extractive answers are quoted from passages without entailment checks.

### Chat, agent and model API

Three processes mirror a hosted assistant, but everything runs locally:

```bash
laris model serve --port 8000                         # model API (OpenAI-compatible)
laris app serve --model-api-url http://127.0.0.1:8000/v1 --model-name laris-core   # chat web UI :8765
laris agent chat                                       # terminal session (also -p "prompt", --resume)
```

The **web UI** has conversation history, streaming answers, tool-call cards, file attach and drag-drop
(PDF, text, scans and images through OCR), a document-corpus panel and a settings panel for the model
API address. The **terminal** session streams text, prints each tool call with a one-line result, asks
before write tools (`y`/`a`lways/`N`) and has `/new /sessions /resume /tools /status /model /write`.
Both share conversations and settings under `artifacts/chat` (config `app.chat_dir`).

Nothing here is hardcoded: ports, workspace, model API, limits, approval policy, prompts and
security patterns come from `configs/default.yaml`, `~/.laris/config.yaml`,
`<project>/.laris/config.yaml`, saved preferences, `LARIS_*` environment variables (nesting with
`__`, JSON for lists; see `.env.example`) and finally the flags, in that order. Credentials are
referenced by environment-variable name only. The prompt, loop, guards and leak policy are described
in `docs/architecture/AGENT_HARNESS.md`; `LARIS.md` is internal policy and is never shown to users.

Tools (JSON-schema arguments, 30 s default timeout, typed errors): `list_files`, `read_file` (txt, md,
pdf, images; scans use tesseract `eng+vie`), `write_file` and `ingest_path` (need approval; writes land
only in `artifacts/chat/output`), `search_corpus`, `answer_question`, `extract_discourse`,
`corpus_status`. Reads are limited to the working folder and uploads. A message stops after 10 steps,
on an identical repeated call, or after the time budget; every session is logged as JSONL.

The client runs the tools and the **model server decides**: it receives `messages` and `tools` at
`POST /v1/chat/completions` (JSON or `stream: true` SSE) and answers with text or `tool_calls`;
`GET /v1/models`, `GET /health` and `POST /v1/embeddings` are also served. Today the backend is a
scripted placeholder that quotes passages (`laris-placeholder`). The trained core model plugs in as a
`ChatProvider` subclass: `laris model serve --backend package.module:ClassName --model-name laris-core`,
with no client change. Set an API key through `--api-key-env` on the server and the same variable name in
the client settings; keys are never stored in files.

#### Policy folder, workflows and integrity

`.laris/` holds the protected prompts, rules and workflows (see `.laris/README.md`).
`laris workflows list|show|check` inspects workflows, run one in chat with `/workflow <name> <request>`;
`laris harness verify` checks the integrity lock, prompts and workflows and `laris harness lock`
refreshes the lock after an owner-approved change. A tampered policy stops every session.

#### Learning: skills from new knowledge and fine-tune data

Ingesting documents creates or refreshes a generated `corpus-*` skill (`laris skills sync` rebuilds
them all); `laris skills lint|add` checks and installs a hand-written one, and the agent can save one
with `save_skill` after approval. Good answers are kept locally under `artifacts/finetune`
(`laris learn stats|export|purge`, `/rate up|down`, `/learn on|off`); the system never trains.

#### Instructions, skills and automatic context compaction

- **`LARIS.md`** (project root) is the internal policy: read at the start of every turn and put in the
  system prompt as confidential, after the optional user-level `~/.laris/LARIS.md` and before
  `.laris/LARIS.md` and the git-ignored `LARIS.local.md` (`prompts.instruction_files`). Edits apply on
  the next message; the files cannot be read through the agent's tools.
- **Skills** live in `.laris/skills/<name>/SKILL.md` (YAML `name` and `description`, Markdown body,
  optional `references/`). Only name and description are in the prompt; the model loads a skill with the
  `use_skill` tool, or the user runs `/<skill-name> request` (terminal and web `/` menu). `laris skills
  list|show|check` inspects and validates them. Project skills override `~/.laris/skills`.
- **Memory** is `.laris/memory/*.md` (short dated notes the skills read first); `save_memory` writes it
  after approval.
- **Autocompact is on by default** (`auto_compact`, `context_window` 32768 tokens, `compact_threshold`
  0.8, all in settings). Before each model call the session estimates its size; above the threshold it
  trims old tool outputs, then replaces older turns with a summary (model-written when a model API is
  connected, otherwise extracted) while keeping recent turns and every tool-call/result pair intact. A
  context-length error from the model triggers one forced compaction and a retry. The original messages
  are archived in `artifacts/chat/archive/`. `/compact [note]` compacts now; `/context` shows usage.
