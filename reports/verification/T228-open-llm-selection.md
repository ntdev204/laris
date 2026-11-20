# T228 — Open-weight LLM selection report

Date read: 2026-11-20. Nothing was downloaded or installed. Every figure below is **as printed on the official
Hugging Face model card**, i.e. a vendor self-report. None was measured by LARIS, none is a LARIS qualification, and
the cards do not always say whether a score was taken in thinking mode. Memory figures marked *(estimate)* are mine
(parameters × bytes per weight, without KV cache) and are not from a source.

Machine: RTX 5070 Ti, 16,303 MiB (`nvidia-smi`). The project venv has `torch 2.14.1` only; `transformers`, `vllm`
and `accelerate` are **not installed**, so every candidate needs a new runtime dependency (owner approval, AGENTS.md).

## Candidates

| Model (card) | Licence | Size | Context | Thinking | GPQA Diamond (card) | Fit in 16 GB *(estimate)* |
|---|---|---|---|---|---|---|
| [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B) | apache-2.0 | 9B dense | 262,144 (up to 1,010,000) | default on; off via `enable_thinking: False` | 81.7 | BF16 ≈ 18 GB no; 8-bit ≈ 9–10 GB yes; 4-bit ≈ 5–6 GB yes |
| [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) | apache-2.0 | 4B dense | 262,144 (up to 1,010,000) | same as 9B | 76.2 | BF16 ≈ 8–9 GB yes |
| [Qwen3-4B-Thinking-2507](https://huggingface.co/Qwen/Qwen3-4B-Thinking-2507) | apache-2.0 | 4.0B (3.6B non-embedding) | 262,144 | thinking only | 65.8 (row "GPQA") | BF16 ≈ 8 GB yes |
| [Gemma 4 26B-A4B-it](https://huggingface.co/google/gemma-4-26B-A4B-it) | apache-2.0 | 25.2B total, 3.8B active (MoE) | 256K | toggle via `<\|think\|>` in system prompt | 82.3 | 4-bit ≈ 14–15 GB, tight with KV cache; all weights must be resident |
| [Gemma 4 E4B-it](https://huggingface.co/google/gemma-4-E4B-it) | apache-2.0 | 4.5B effective (8B with embeddings) | 128K | toggle, as above | 58.6 | BF16 ≈ 16 GB no; 8-bit yes |
| [Phi-4-mini-reasoning](https://huggingface.co/microsoft/Phi-4-mini-reasoning) | MIT | 3.8B | 128K | not stated | 52.0 | yes |

Notes taken from the cards:

- **Phi-4-mini-reasoning is rejected**: the card states it is "designed and tested for math reasoning only" and
  calls GPQA Diamond "a wide range of mathematical questions". It does not fit a general science-reasoning role.
- **Code is not the focus of any card**; none is code-only. The Qwen and Gemma cards list coding among many
  capabilities. The owner asked for a science-reasoning model "no code"; no candidate is code-specific, so this
  criterion does not separate them.
- The Qwen3.5 cards describe a general **vision-language** model; the vision tower is unused for LARIS text.
- Gemma 4 E-series: disabled thinking omits the empty thought block; on 26B-A4B it still emits one (card text).
  The Qwen3.5 cards say the `/think` and `/nothink` soft switch is **not** supported.

## Runtime each needs (new dependency, owner approval)

| Option | Needed by | What the cards say | Cost |
|---|---|---|---|
| `transformers` (+`accelerate`) | all | Qwen3.5: "latest `transformers` is required"; Gemma 4: "latest version of Transformers"; Qwen3-4B-Thinking: ≥4.51; Phi: 4.51.3 | Python only, smallest change to `laris-model serve`; BF16 loads, 4/8-bit need `bitsandbytes` (another dependency) |
| `llama.cpp` server (GGUF) | Qwen3, Gemma 4 (cards name llama.cpp as supported; GGUF quants are published on HF by third parties and by Google for E4B) | Qwen3.5 card names SGLang/vLLM/KTransformers, not llama.cpp | Separate binary, not Python; quantisation is simple; third-party GGUF quants are unaudited artefacts |
| `vllm` | Qwen3-4B-Thinking (≥0.8.5), Qwen3.5 (main branch) | Qwen3.5 requires an unreleased main branch | Heavy install; unstable pin for Qwen3.5; not recommended on one 16 GB GPU |

## Recommendation (for the owner to accept or change)

1. **Primary: Qwen3.5-9B**, Apache-2.0, at 8-bit or 4-bit. Highest card GPQA among candidates that fit comfortably
   (81.7), general scope, long context for retrieved vault passages, thinking switchable per request, which suits
   the harness loop (T232: think for the draft, skip for the evidence check).
2. **Fallback: Qwen3.5-4B in BF16** (76.2): fits without quantisation, so no `bitsandbytes`.
3. Gemma 4 26B-A4B has a similar card score (82.3) but only fits at 4-bit with little room; not recommended first.
4. **Runtime: `transformers` + `accelerate`** (+ `bitsandbytes` only if 9B is quantised in-process). It is the
   smallest change to the existing Python model service and matches what every card documents. `llama.cpp` is the
   alternative if the owner prefers GGUF and a separate process.

Caveats the owner should weigh: the Qwen3.5 cards give no version numbers, only "latest" or "main"; the GPQA
numbers are not comparable across vendors without knowing the mode and sampling used; vision weights add download
size; thinking mode produces long outputs, so latency on this GPU is unmeasured. A real check (T231) must measure
tokens per second, memory, and quality on LARIS questions before anything is claimed.

## Owner decision required (T228 validation)

Write in the task Result or reply: (a) the model, (b) the quantisation, (c) the runtime and the dependency
approved (names and versions). T231 stays blocked until then.

## Sources

- Qwen3.5-9B card: https://huggingface.co/Qwen/Qwen3.5-9B
- Qwen3.5-4B card: https://huggingface.co/Qwen/Qwen3.5-4B
- Qwen3-4B-Thinking-2507 card: https://huggingface.co/Qwen/Qwen3-4B-Thinking-2507
- Gemma 4 26B-A4B-it card: https://huggingface.co/google/gemma-4-26B-A4B-it
- Gemma 4 E4B-it card: https://huggingface.co/google/gemma-4-E4B-it
- Phi-4-mini-reasoning card: https://huggingface.co/microsoft/Phi-4-mini-reasoning
- Local checks: `nvidia-smi`; `.venv/bin/python` package listing (2026-11-20)
