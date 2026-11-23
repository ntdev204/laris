#!/usr/bin/env python3
"""STEM benchmark data, leakage scan and the bare-model baseline (T275, ADR-026).

    python scripts/stem_benchmarks.py download        # network: pinned sources to data/benchmarks
    python scripts/stem_benchmarks.py split           # seeded dev / sealed splits, manifest (once)
    python scripts/stem_benchmarks.py scan NOTES_DIR  # 13-gram scan of notes against all items (B6)
    docker/laris.sh up                                # LARIS_ENGINE_PORT in docker/laris.env: vLLM
    python scripts/stem_benchmarks.py baseline --mode thinking_off [--bench math500] [--limit N]
    python scripts/stem_benchmarks.py solver          # T276: model-free solver path on dev splits
    python scripts/stem_benchmarks.py harness [--bench B] [--limit N]  # T278: router and harness

Settings come from `configs/stem-benchmarks.json` (`--config`). `baseline` reads the development
splits only and sends them to the engine of `engine.kind`: `vllm_http`, the vLLM server of the
compose stack (`docker/compose.chat.yaml`, T282: the one engine for chat and evaluation, owner
2026-11-23; its settings live there, the summary records what the server reports), or
`transformers`, in-process, kept for parity checks. Per-item records go to
`data/benchmarks/runs/<run>.jsonl` (outside Git), the summary to `--summary`. A record holds
ids, the extracted answer (a letter for multiple choice), scores and cost, never a question or an
option. Inference only: no gradient, no optimiser. A baseline of the
bare model is not a qualification of anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from laris.research.stem import answers, data, leakage, stats  # noqa: E402


def _config(path: str) -> Dict[str, Any]:
    return data.load_config(ROOT / path)


def cmd_download(args: argparse.Namespace) -> int:
    provenance = data.download(_config(args.config), ROOT)
    for name, source in provenance["sources"].items():
        print(name, source["revision"][:12], len(source["files"]), "files")
    return 0


def cmd_split(args: argparse.Namespace) -> int:
    manifest = data.write_splits(_config(args.config), ROOT)
    for bench, parts in manifest["benchmarks"].items():
        print(bench, {part: entry["items"] for part, entry in parts.items()})
    return 0


def _all_items(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every benchmark item (dev and sealed, MMLU-Pro validation too): the scan's reference set.
    Reads the raw files, not the sealed splits, so it needs no sealed-run order."""
    raw = ROOT / config["data_dir"] / "raw"
    seed = int(config["option_shuffle_seed"])
    items = data.read_math500(raw) + data.read_math_train(raw)
    items += data.read_mmlu_pro(raw, config["splits"]["mmlu_pro_stem"]["categories"])
    items += data.read_gpqa(raw, "gpqa_main.csv", seed) + data.read_gpqa(
        raw, "gpqa_diamond.csv", seed
    )
    return items


def cmd_scan(args: argparse.Namespace) -> int:
    config = _config(args.config)
    cfg = config["leakage"]
    hits = leakage.scan_folder(
        Path(args.folder), _all_items(config), int(cfg["ngram"]), cfg["note_suffixes"]
    )
    print(json.dumps({"ngram": cfg["ngram"], "hits": len(hits), "detail": hits}, indent=2))
    return 1 if hits else 0


# -- baseline ------------------------------------------------------------------------------------


def prompt_for(item: Dict[str, Any], prompts: Dict[str, str]) -> str:
    if not item["options"]:
        return prompts["math"].replace("{question}", item["question"])
    letters = data.LETTERS[: len(item["options"])]
    options = "\n".join(f"{letters[i]}. {text}" for i, text in enumerate(item["options"]))
    return (
        prompts["choice"]
        .replace("{letters}", ", ".join(letters))
        .replace("{question}", item["question"])
        .replace("{options}", options)
    )


def score(item: Dict[str, Any], answer_text: str, eq_cfg: Dict[str, Any]) -> Dict[str, Any]:
    if item["options"]:
        extracted = answers.extract_choice(answer_text, data.LETTERS[: len(item["options"])])
        correct = extracted == item["answer"]
    else:
        extracted = answers.extract_math_answer(answer_text)
        correct = answers.math_equivalent(
            extracted, item["answer"], float(eq_cfg["numeric_rel_tol"]), float(eq_cfg["timeout_s"])
        )
    return {"extracted": extracted, "correct": bool(correct)}


class Generator:
    """Batched generation with `transformers`, left padding, inference mode."""

    def __init__(self, cfg: Dict[str, Any]) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        self.torch = torch
        kwargs: Dict[str, Any] = {"dtype": getattr(torch, cfg["dtype"]), "device_map": "cuda:0"}
        if cfg["quantization"] != "none":  # "8bit" | "4bit" (bitsandbytes), "none" = dtype only
            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_8bit=cfg["quantization"] == "8bit",
                load_in_4bit=cfg["quantization"] == "4bit",
                bnb_4bit_compute_dtype=getattr(torch, cfg["dtype"]),
            )
        self.tokenizer = AutoTokenizer.from_pretrained(cfg["model_id"], padding_side="left")
        self.model = AutoModelForCausalLM.from_pretrained(cfg["model_id"], **kwargs).eval()
        vocab = self.tokenizer.get_vocab()
        self.stops = [
            i
            for i in [
                self.tokenizer.eos_token_id,
                vocab.get("<|im_end|>"),
                vocab.get("<|endoftext|>"),
            ]
            if isinstance(i, int)
        ]

    def run(self, prompts: List[str], mode: Dict[str, Any], seed: int) -> List[Dict[str, Any]]:
        torch = self.torch
        texts = [
            self.tokenizer.apply_chat_template(
                [{"role": "user", "content": p}],
                add_generation_prompt=True,
                tokenize=False,
                enable_thinking=bool(mode["enable_thinking"]),
            )
            for p in prompts
        ]
        batch = self.tokenizer(texts, return_tensors="pt", padding=True, add_special_tokens=False)
        batch = batch.to(self.model.device)
        prompt_lengths = batch["attention_mask"].sum(dim=1).tolist()
        torch.manual_seed(seed)
        torch.cuda.reset_peak_memory_stats()
        start = time.perf_counter()
        with torch.inference_mode():
            out = self.model.generate(
                **batch,
                max_new_tokens=int(mode["max_new_tokens"]),
                do_sample=True,
                temperature=float(mode["temperature"]),
                top_p=float(mode["top_p"]),
                top_k=int(mode["top_k"]),
                eos_token_id=self.stops,
                pad_token_id=self.tokenizer.pad_token_id or self.stops[0],
            )
        seconds = time.perf_counter() - start
        peak = int(torch.cuda.max_memory_allocated())
        width = batch["input_ids"].shape[1]
        results = []
        for row, plen in zip(out, prompt_lengths):
            new = row[width:].tolist()
            ended = any(t in self.stops for t in new)
            if ended:
                new = new[: min(new.index(t) for t in self.stops if t in new)]
            results.append(
                {
                    "text": self.tokenizer.decode(new, skip_special_tokens=True),
                    "prompt_tokens": int(plen),
                    "generated_tokens": len(new),
                    "truncated": not ended,
                    "batch_seconds": seconds,
                    "peak_vram_bytes": peak,
                }
            )
        return results


class HttpEngine:
    """Requests to an OpenAI-compatible server (vLLM, continuous batching), `concurrency` at once.

    `seconds` of an item is its request's wall time under that load; the server holds its GPU
    memory from the start, so `peak_vram_bytes` is the GPU memory in use when the run began."""

    def __init__(self, cfg: Dict[str, Any], model_id: str) -> None:
        self.url = f"http://{cfg['host']}:{engine_port(cfg)}/v1"
        self.model_id = model_id
        self.concurrency = int(cfg["concurrency"])
        self.timeout_s = float(cfg["timeout_s"])
        self.vram = gpu_memory_used_bytes()

    def identity(self) -> Dict[str, Any]:
        """What the server says it serves (model, revision root, context, version)."""
        import urllib.request

        root = self.url.rstrip("/").removesuffix("/v1")
        with urllib.request.urlopen(self.url.rstrip("/") + "/models", timeout=30) as response:
            models = json.loads(response.read())["data"]
        with urllib.request.urlopen(root + "/version", timeout=30) as response:
            version = json.loads(response.read()).get("version", "")
        entry = next((m for m in models if m["id"] == self.model_id), {})
        if not entry:
            raise SystemExit(f"the engine does not serve {self.model_id}")
        return {
            "model": entry["id"],
            "max_model_len": entry.get("max_model_len"),
            "vllm": version,
        }

    def one(self, prompt: str, mode: Dict[str, Any], seed: int) -> Dict[str, Any]:
        import urllib.request

        body = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": int(mode["max_new_tokens"]),
            "temperature": float(mode["temperature"]),
            "top_p": float(mode["top_p"]),
            "top_k": int(mode["top_k"]),
            "seed": seed,
            "chat_template_kwargs": {"enable_thinking": bool(mode["enable_thinking"])},
        }
        request = urllib.request.Request(
            self.url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        start = time.perf_counter()
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            reply = json.loads(response.read())
        seconds = time.perf_counter() - start
        choice = reply["choices"][0]
        message = choice["message"]
        text = message.get("content") or ""
        if message.get("reasoning_content"):  # a server with a reasoning parser splits it out
            text = "<think>" + message["reasoning_content"] + "</think>" + text
        return {
            "text": text,
            "prompt_tokens": int(reply["usage"]["prompt_tokens"]),
            "generated_tokens": int(reply["usage"]["completion_tokens"]),
            "truncated": choice.get("finish_reason") == "length",
            "seconds": seconds,
            "peak_vram_bytes": self.vram,
        }


def engine_port(cfg: Dict[str, Any]) -> int:
    """The engine's port: `port_variable` in `port_file` (docker/laris.env), the one place it is
    set; docker/laris.sh opens the same port."""
    path = ROOT / cfg["port_file"]
    name = cfg["port_variable"]
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key.strip() == name and value.strip().strip("\"'").isdigit():
                return int(value.strip().strip("\"'"))
    raise SystemExit(f"set {name} in {cfg['port_file']} (see docker/laris.env.example)")


def gpu_memory_used_bytes() -> int:
    """GPU memory in use on device 0 (`nvidia-smi`), 0 when it cannot be read."""
    import subprocess

    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-i", "0"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
        return int(float(out.strip().splitlines()[0]) * 1024 * 1024)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    from laris.model.inference.open_llm import split_reasoning

    config = _config(args.config)
    base = config["baseline"]
    mode = base["modes"][args.mode]
    run = args.run or f"baseline-{args.mode}"
    out_dir = ROOT / config["data_dir"] / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{run}.jsonl"
    done = set()
    if out_path.exists():  # resume: items already scored are kept
        done = {json.loads(line)["id"] for line in out_path.read_text().splitlines() if line}
    if args.quantization:
        base = dict(base, quantization=args.quantization)
    engine_cfg = config["engine"]
    engine_kind = args.engine or engine_cfg["kind"]
    batch_size = int(args.batch_size or mode["batch_size"])
    fraction = float(mode["sample_fraction"])
    work: List[Any] = []
    for bench in args.bench or list(data.BENCHMARKS):
        items = data.load_items(config, ROOT, bench, "dev")
        if fraction < 1.0:  # seeded, stratified by category (the same rule as the MMLU-Pro split)
            items = data.stratified_sample(items, fraction, int(config["split_seed"]))
        if args.limit:
            items = items[: args.limit]
        work += [(bench, i) for i in items if i["id"] not in done]
    seed0 = int(base["generation_seed"])

    def record(bench: str, item: Dict[str, Any], output: Dict[str, Any], share: float) -> str:
        _, answer_text = split_reasoning(output["text"])
        scored = score(item, answer_text, config["equivalence"])
        cost = stats.CostRecord(
            seconds=share,
            prompt_tokens=output["prompt_tokens"],
            generated_tokens=output["generated_tokens"],
            model_calls=1,
            solver_calls=0,
            peak_vram_bytes=output["peak_vram_bytes"],
        )
        return json.dumps(
            {
                "id": item["id"],
                "bench": bench,
                "category": item["category"],
                "mode": args.mode,
                "engine": engine_kind,
                "extracted": scored["extracted"],  # a letter for multiple choice
                "correct": scored["correct"],
                "truncated": output["truncated"],
                "finished_at": time.time(),
                "cost": cost.as_dict(),
            }
        )

    if engine_kind == "vllm_http":
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed

        engine = HttpEngine(engine_cfg, base["model_id"])
        served = engine.identity()
        lock, count = threading.Lock(), 0
        with ThreadPoolExecutor(max_workers=engine.concurrency) as pool:
            futures = {
                pool.submit(
                    engine.one,
                    prompt_for(item, base["prompts"]),
                    mode,
                    seed0 + int(hashlib.sha256(item["id"].encode()).hexdigest()[:8], 16) % 100000,
                ): (bench, item)
                for bench, item in work
            }
            for future in as_completed(futures):
                bench, item = futures[future]
                output = future.result()
                line = record(bench, item, output, output["seconds"])
                with lock, open(out_path, "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
                    count += 1
                if count % 50 == 0 or count == len(work):
                    print(f"{count}/{len(work)}", flush=True)
    else:
        generator = Generator(base)
        # similar prompt lengths in one batch: less padding
        work.sort(key=lambda w: (w[0], len(prompt_for(w[1], base["prompts"]))))
        for start in range(0, len(work), batch_size):
            chunk = work[start : start + batch_size]
            outputs = generator.run(
                [prompt_for(i, base["prompts"]) for _, i in chunk], mode, seed0 + start
            )
            with open(out_path, "a", encoding="utf-8") as handle:
                for (bench, item), output in zip(chunk, outputs):
                    share = output["batch_seconds"] / len(chunk)
                    handle.write(record(bench, item, output, share) + "\n")
            print(
                f"{start + len(chunk)}/{len(work)} {outputs[0]['batch_seconds']:.0f}s", flush=True
            )
    summary = summarise_run(out_path, config, args.mode, batch_size, base["quantization"])
    summary["engine"] = engine_kind
    if engine_kind == "vllm_http":
        summary["engine_server"] = served
    if args.summary:
        Path(args.summary).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


def summarise_run(
    path: Path, config: Dict[str, Any], mode: str, batch_size: int, quantization: str
) -> Dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line]
    answers_file = ROOT / "src/laris/research/stem/answers.py"
    out: Dict[str, Any] = {
        "run": path.stem,
        "mode": mode,
        "model_id": config["baseline"]["model_id"],
        "settings": config["baseline"]["modes"][mode],
        "batch_size": batch_size,
        "sample_fraction": config["baseline"]["modes"][mode]["sample_fraction"],
        "quantization": quantization,
        "dtype": config["baseline"]["dtype"],
        "equivalence_protocol": answers.EQUIVALENCE_PROTOCOL,
        "answers_py_sha256": hashlib.sha256(answers_file.read_bytes()).hexdigest(),
        "benchmarks": {},
    }
    for bench in data.BENCHMARKS:
        bench_rows = [r for r in rows if r["bench"] == bench]
        if not bench_rows:
            continue
        entry = stats.summarise(bench_rows)
        entry["categories"] = {
            c: stats.summarise([r for r in bench_rows if r["category"] == c])
            for c in sorted({r["category"] for r in bench_rows})
        }
        out["benchmarks"][bench] = entry
    return out


def report_tables(summaries: List[Dict[str, Any]]) -> str:
    """Markdown tables of run summaries: scores, intervals and cost; no item text."""
    lines = [
        "| Run | Benchmark | Items | Correct | Accuracy | Wilson 95 % | Unparsed | Truncated "
        "| s/item median | s/item p95 | Gen. tokens median | p95 | Peak VRAM GB |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for summary in summaries:
        for bench, b in summary["benchmarks"].items():
            lines.append(
                f"| {summary['mode']} | {bench} | {b['items']} | {b['correct']} "
                f"| {100 * b['accuracy']:.1f} % "
                f"| {100 * b['wilson_low']:.1f}-{100 * b['wilson_high']:.1f} "
                f"| {b['unparsed']} | {b['truncated']} | {b['seconds_median']:.1f} "
                f"| {b['seconds_p95']:.1f} | {b['generated_tokens_median']:.0f} "
                f"| {b['generated_tokens_p95']:.0f} | {b['peak_vram_bytes'] / 1e9:.1f} |"
            )
    lines += [
        "",
        "| Run | Benchmark | Category | Items | Accuracy | Wilson 95 % |",
        "|---|---|---|---|---|---|",
    ]
    for summary in summaries:
        for bench, b in summary["benchmarks"].items():
            for category, c in b["categories"].items():
                lines.append(
                    f"| {summary['mode']} | {bench} | {category} | {c['items']} "
                    f"| {100 * c['accuracy']:.1f} % "
                    f"| {100 * c['wilson_low']:.1f}-{100 * c['wilson_high']:.1f} |"
                )
    return "\n".join(lines) + "\n"


def cmd_solver(args: argparse.Namespace) -> int:
    """T276: the model-free path (strict patterns -> deterministic solver) on the development
    splits. An item counts as answered only when the solver verified its result; precision is
    over answered items. No model, no GPU; records hold ids, pattern, status and the score."""
    from laris.model.solver import SolverSettings
    from laris.research.stem.formalise import answer_model_free
    from laris.shared.config.loader import load_runtime_config

    config = _config(args.config)
    eq = config["equivalence"]
    settings = SolverSettings.from_config(load_runtime_config(ROOT).model_service)
    out_dir = ROOT / config["data_dir"] / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    records, summary = [], {"run": args.run, "solver": {}, "benchmarks": {}}
    started = time.time()
    for bench in args.bench or list(data.BENCHMARKS):
        items = data.load_items(config, ROOT, bench, "dev")
        counts = {"items": len(items), "formalised": 0, "answered": 0, "correct": 0}
        by_pattern: Dict[str, Dict[str, int]] = {}
        for item in items:
            began = time.time()
            out = answer_model_free(item, settings)
            seconds = round(time.time() - began, 4)
            correct = None
            if out["answer"] is not None:
                correct = bool(
                    answers.math_equivalent(
                        out["answer"], item["answer"], eq["numeric_rel_tol"], eq["timeout_s"]
                    )
                )
            if out["pattern"]:
                counts["formalised"] += 1
                empty = {"formalised": 0, "answered": 0, "correct": 0}
                slot = by_pattern.setdefault(out["pattern"], empty)
                slot["formalised"] += 1
                if out["answer"] is not None:
                    slot["answered"] += 1
                    slot["correct"] += int(bool(correct))
            if out["answer"] is not None:
                counts["answered"] += 1
                counts["correct"] += int(bool(correct))
            records.append(
                {
                    "bench": bench,
                    "id": item["id"],
                    "pattern": out["pattern"],
                    "status": out["status"],
                    "correct": correct,
                    "seconds": seconds,
                }
            )
        answered = counts["answered"]
        counts["precision"] = round(counts["correct"] / answered, 4) if answered else None
        counts["coverage"] = round(answered / len(items), 4) if items else 0.0
        interval = stats.wilson_interval(counts["correct"], answered) if answered else None
        counts["precision_wilson95"] = [round(v, 4) for v in interval] if interval else None
        counts["patterns"] = by_pattern
        summary["benchmarks"][bench] = counts
    from laris.model.solver.engine import engine_versions

    summary["solver"] = {**engine_versions(), "codata_sha256": settings.codata_sha256}
    summary["wall_seconds"] = round(time.time() - started, 1)
    run = args.run or "solver-dev"
    path = out_dir / f"{run}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    summary_path = out_dir / f"{run}.summary.json"
    summary_path.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


def retrieve_notes(
    hcfg: Dict[str, Any], work: List[Any], out_dir: Path, run: str
) -> Tuple[Dict[str, List[str]], Dict[str, List[str]], float, str]:
    """Passages of the frozen brain snapshot for every item in `work` (pairs of bench and item),
    through the server's own retrieval (`laris-server brain retrieve`), queried with the question
    and its options as in T277. Returns the passages per id, the certain Claims among them per id
    (only with `retrieval.source_classes`, T285: the server's rule decides), the wall seconds and
    the snapshot hash. The query file lives in the ignored run folder and is deleted afterwards."""
    import os
    import subprocess

    rcfg = hcfg["retrieval"]
    brain = json.loads((ROOT / rcfg["brain_config"]).read_text(encoding="utf-8"))
    folder = ROOT / brain["data_dir"] / "snapshots" / rcfg["snapshot"]
    snapshot = json.loads((folder / "snapshot.json").read_text("utf-8"))["snapshot_sha256"]
    if not work:
        return {}, {}, 0.0, snapshot
    gate = brain["gate"]
    env = {k: v for k, v in os.environ.items() if not k.startswith("LARIS_SERVER__")}
    env.update(
        {
            "LARIS_SERVER__MAIN_BRAIN_DIR": str(folder / "vault"),
            "LARIS_SERVER__MAIN_BRAIN_MIN_SUPPORT": str(gate["min_support"]),
            "LARIS_SERVER__MAIN_BRAIN_MIN_EQUIVALENCE": str(gate["min_equivalence"]),
            "LARIS_SERVER__MAIN_BRAIN_SUBJECT_OVERLAP": str(gate["subject_overlap"]),
            "LARIS_SERVER__MAIN_BRAIN_SEARCH_DEPTH": str(gate["search_depth"]),
            "LARIS_SERVER__MAIN_BRAIN_MAX_BYTES": str(gate["max_bytes"]),
        }
    )
    queries = out_dir / f"{run}.queries.jsonl"
    with queries.open("w", encoding="utf-8") as handle:
        for _, item in work:
            query = item["question"] + " " + " ".join(item.get("options") or [])
            handle.write(json.dumps({"id": item["id"], "query": query}) + "\n")
    began = time.perf_counter()
    try:
        result = subprocess.run(
            [str(ROOT / rcfg["server_bin"]), "brain", "retrieve", str(queries), str(rcfg["k"])]
            + ([str(ROOT / rcfg["source_classes"])] if rcfg.get("source_classes") else []),
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )
    finally:
        queries.unlink()
    seconds = time.perf_counter() - began
    notes, certain = {}, {}
    for line in result.stdout.splitlines():
        row = json.loads(line)
        notes[row["id"]] = [hit["text"] for hit in row["hits"]]
        certain[row["id"]] = [hit["text"] for hit in row["hits"] if hit.get("certain") is True]
    return notes, certain, seconds, snapshot


class VramSampler:
    """The largest GPU memory in use, read by `nvidia-smi` every `period_s` while running."""

    def __init__(self, period_s: float = 1.0) -> None:
        import threading

        self.period_s = period_s
        self.peak = gpu_memory_used_bytes()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
        while not self._stop.wait(self.period_s):
            self.peak = max(self.peak, gpu_memory_used_bytes())

    def __enter__(self) -> "VramSampler":
        self._thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self._stop.set()
        self._thread.join(5)


def cmd_harness(args: argparse.Namespace) -> int:
    """T278: the evaluation profile (router, model-free path, notes, draft, formalisation, checks,
    review) on the development splits, against the T275 bare-model records of the same items.
    Records hold ids, class, steps, answers (a letter or a value) and cost; never item text."""
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from laris.model.solver import SolverError, SolverSettings
    from laris.model.solver import run as solver_run
    from laris.research.stem.formalise import answer_model_free
    from laris.research.stem.harness import Harness, summarise_records
    from laris.research.stem.router import route
    from laris.shared.config.loader import load_runtime_config

    revision = code_revision()  # the code this run executes, taken before it starts
    config = _config(args.config)
    base, hcfg = config["baseline"], config["harness"]
    mode = base["modes"][hcfg["mode"]]
    run = args.run or "harness-dev"
    out_dir = ROOT / config["data_dir"] / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{run}.jsonl"
    done = set()
    if out_path.exists():  # resume: items already scored are kept
        done = {json.loads(line)["id"] for line in out_path.read_text().splitlines() if line}
    work: List[Any] = []
    for bench in args.bench or list(data.BENCHMARKS):
        items = data.load_items(config, ROOT, bench, "dev")
        if args.limit:
            items = items[: args.limit]
        work += [(bench, i) for i in items if i["id"] not in done]
    wanted = [
        (b, i) for b, i in work if route(i, hcfg["router"]).cls in hcfg["retrieval"]["classes"]
    ]
    notes, certain, retrieval_s, snapshot = retrieve_notes(hcfg, wanted, out_dir, run)
    retrieval_share = retrieval_s / len(wanted) if wanted else 0.0
    print(f"retrieval: {len(wanted)} items, {retrieval_s:.1f} s", flush=True)

    settings = SolverSettings.from_config(load_runtime_config(ROOT).model_service)
    gate = threading.BoundedSemaphore(int(hcfg["solver_check"]["max_concurrency"]))

    def solve(problem: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
        with gate:
            try:
                result = solver_run(problem, settings)
            except SolverError as exc:
                return None, f"refused:{exc.code}"
        return result, str(result.get("status"))

    def model_free(item: Dict[str, Any]) -> Dict[str, Any]:
        with gate:
            return answer_model_free(item, settings)

    engine = HttpEngine(config["engine"], base["model_id"])
    served = engine.identity()

    def model(prompt: str, seed: int, max_tokens: int) -> Dict[str, Any]:
        return engine.one(prompt, dict(mode, max_new_tokens=max_tokens), seed)

    free = model_free if hcfg["model_free"] else None
    harness = Harness(hcfg, base, model, solve, config["equivalence"], free)
    seed0 = int(base["generation_seed"])
    eq = config["equivalence"]

    def one(bench: str, item: Dict[str, Any]) -> str:
        began = time.perf_counter()
        seed = seed0 + int(hashlib.sha256(item["id"].encode()).hexdigest()[:8], 16) % 100000
        has_notes = item["id"] in notes
        trace = harness.answer(item, seed, notes.get(item["id"]), certain.get(item["id"]))
        seconds = time.perf_counter() - began + (retrieval_share if has_notes else 0.0)
        final = score_answer(item, trace.final, eq)
        draft = score_answer(item, trace.draft, eq) if trace.draft is not None else False
        cost = stats.CostRecord(
            seconds=seconds,
            prompt_tokens=trace.prompt_tokens,
            generated_tokens=trace.generated_tokens,
            model_calls=trace.model_calls,
            solver_calls=trace.solver_calls,
            peak_vram_bytes=sampler.peak,
        )
        record = {
            "id": item["id"],
            "bench": bench,
            "category": item["category"],
            "mode": hcfg["mode"],
            "extracted": trace.final,
            "correct": final,
            "draft_correct": draft,
            "finished_at": time.time(),
            "cost": cost.as_dict(),
        }
        trace_dict = trace.as_dict()
        for key in ("prompt_tokens", "generated_tokens", "model_calls", "solver_calls"):
            trace_dict.pop(key)
        record.update(trace_dict)
        return json.dumps(record)

    lock, count = threading.Lock(), 0
    with VramSampler() as sampler, ThreadPoolExecutor(max_workers=int(hcfg["concurrency"])) as pool:
        futures = [pool.submit(one, bench, item) for bench, item in work]
        for future in as_completed(futures):
            line = future.result()
            with lock, open(out_path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                count += 1
            if count % 50 == 0 or count == len(work):
                print(f"{count}/{len(work)}", flush=True)
        peak = sampler.peak

    rows = [json.loads(line) for line in out_path.read_text().splitlines() if line]
    baseline_path = ROOT / config["data_dir"] / "runs" / args.baseline_run
    baseline = {}
    if baseline_path.exists():
        for line in baseline_path.read_text().splitlines():
            if line:
                row = json.loads(line)
                baseline[row["id"]] = bool(row["correct"])
    summary: Dict[str, Any] = {
        "run": run,
        "mode": hcfg["mode"],
        "model_id": base["model_id"],
        "settings": mode,
        "engine_server": served,
        "code_revision": revision,
        "brain_snapshot_sha256": snapshot,
        "harness_config_sha256": hashlib.sha256(
            json.dumps(hcfg, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "equivalence_protocol": answers.EQUIVALENCE_PROTOCOL,
        "baseline_run": args.baseline_run if baseline else None,
        "peak_vram_bytes_sampled": peak,
        "benchmarks": {},
    }
    for bench in data.BENCHMARKS:
        bench_rows = [r for r in rows if r["bench"] == bench]
        if not bench_rows:
            continue
        entry = summarise_records(bench_rows, baseline or None)
        entry["classes"] = {
            c: summarise_records([r for r in bench_rows if r["cls"] == c], baseline or None)
            for c in sorted({r["cls"] for r in bench_rows})
        }
        summary["benchmarks"][bench] = entry
    summary_path = out_dir / f"{run}.summary.json"
    summary_path.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


def code_revision() -> str:
    """HEAD, with `+changes` when tracked files differ from it."""
    import subprocess

    def git(*cmd: str) -> str:
        return subprocess.run(
            ["git", *cmd], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()

    dirty = git("status", "--porcelain", "--untracked-files=no")
    return git("rev-parse", "HEAD") + ("+changes" if dirty else "")


def score_answer(item: Dict[str, Any], answer: Optional[str], eq_cfg: Dict[str, Any]) -> bool:
    """Whether an extracted answer (a letter, or a MATH value) is right under `math-equiv-1`."""
    if answer is None:
        return False
    if item["options"]:
        return bool(answer == item["answer"])
    return bool(
        answers.math_equivalent(
            answer, item["answer"], float(eq_cfg["numeric_rel_tol"]), float(eq_cfg["timeout_s"])
        )
    )


def harness_tables(summary: Dict[str, Any]) -> str:
    """Markdown tables of a harness summary: per benchmark and class against T275, steps, cost."""

    def pct(x: float) -> str:
        return f"{100 * x:.1f} %"

    lines = [
        "| Benchmark | Class | Items | Harness | Wilson 95 % | T275 same items | Gained | Lost "
        "| Draft | Model calls | Solver calls | s median | s p95 | Gen. tokens median |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for bench, b in summary["benchmarks"].items():
        for name, c in [("all", b)] + sorted(b["classes"].items()):
            base = c.get("baseline") or {}
            lines.append(
                f"| {bench} | {name} | {c['items']} | {c['correct']} ({pct(c['accuracy'])}) "
                f"| {pct(c['wilson_low'])}-{pct(c['wilson_high'])} "
                f"| {base.get('correct', '-')} ({pct(base.get('accuracy', 0.0))}) "
                f"| {base.get('gained', '-')} | {base.get('lost', '-')} | {c['draft_correct']} "
                f"| {c['model_calls_mean']:.2f} | {c['solver_calls_mean']:.2f} "
                f"| {c['seconds_median']:.1f} | {c['seconds_p95']:.1f} "
                f"| {c['generated_tokens_median']:.0f} |"
            )
    lines += ["", "| Benchmark | Final answer from | Items | Correct |", "|---|---|---|---|"]
    for bench, b in summary["benchmarks"].items():
        for source, entry in sorted(b["final_from"].items()):
            lines.append(f"| {bench} | {source} | {entry['items']} | {entry['correct']} |")
    lines += [
        "",
        "| Benchmark | Review | Wrong to right | Right to wrong | Unchanged verdict |",
        "|---|---|---|---|---|",
    ]
    for bench, b in summary["benchmarks"].items():
        for how, flips in sorted(b["review_flips"].items()):
            lines.append(
                f"| {bench} | {how} | {flips['to_right']} | {flips['to_wrong']} | {flips['same']} |"
            )
    return "\n".join(lines) + "\n"


def cmd_harness_report(args: argparse.Namespace) -> int:
    print(harness_tables(json.loads(Path(args.summary).read_text(encoding="utf-8"))), end="")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    summaries = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.summaries]
    print(report_tables(summaries), end="")
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="configs/stem-benchmarks.json")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("download").set_defaults(func=cmd_download)
    sub.add_parser("split").set_defaults(func=cmd_split)
    scan = sub.add_parser("scan")
    scan.add_argument("folder")
    scan.set_defaults(func=cmd_scan)
    base = sub.add_parser("baseline")
    base.add_argument("--mode", required=True, choices=["thinking_off", "thinking_on"])
    base.add_argument("--bench", action="append", choices=list(data.BENCHMARKS))
    base.add_argument("--limit", type=int, default=0)
    base.add_argument("--batch-size", type=int, default=0)
    base.add_argument("--run", default="")
    base.add_argument("--quantization", choices=["none", "8bit", "4bit"], default="")
    base.add_argument("--engine", choices=["vllm_http", "transformers"], default="")
    base.add_argument("--summary", default="")
    base.set_defaults(func=cmd_baseline)
    solver = sub.add_parser("solver")
    solver.add_argument("--bench", action="append", choices=list(data.BENCHMARKS))
    solver.add_argument("--run", default="")
    solver.set_defaults(func=cmd_solver)
    harness = sub.add_parser("harness")
    harness.add_argument("--bench", action="append", choices=list(data.BENCHMARKS))
    harness.add_argument("--limit", type=int, default=0)
    harness.add_argument("--run", default="")
    harness.add_argument("--baseline-run", default="baseline-thinking_off.jsonl")
    harness.set_defaults(func=cmd_harness)
    hrep = sub.add_parser("harness-report")
    hrep.add_argument("summary")
    hrep.set_defaults(func=cmd_harness_report)
    rep = sub.add_parser("report")
    rep.add_argument("summaries", nargs="+")
    rep.set_defaults(func=cmd_report)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
