#!/usr/bin/env python3
"""STEM benchmark data, leakage scan and the bare-model baseline (T275, ADR-026).

    python scripts/stem_benchmarks.py download        # network: pinned sources to data/benchmarks
    python scripts/stem_benchmarks.py split           # seeded dev / sealed splits, manifest (once)
    python scripts/stem_benchmarks.py scan NOTES_DIR  # 13-gram scan of notes against all items (B6)
    python scripts/stem_benchmarks.py baseline --mode thinking_off [--bench math500] [--limit N]

Settings come from `configs/stem-benchmarks.json` (`--config`). `baseline` reads the development
splits only; its per-item records go to `data/benchmarks/runs/<run>.jsonl` (outside Git) and its
summary to `--summary`. A record holds ids, the extracted answer (a letter for multiple choice),
scores and cost, never a question or an option. It loads the model with `transformers` and
generates: inference only, no gradient, no optimiser. A baseline of the bare model is not a
qualification of anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

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
    generator = Generator(base)
    batch_size = int(args.batch_size or mode["batch_size"])
    fraction = float(mode["sample_fraction"])
    for bench in args.bench or list(data.BENCHMARKS):
        items = data.load_items(config, ROOT, bench, "dev")
        if fraction < 1.0:  # seeded, stratified by category (the same rule as the MMLU-Pro split)
            items = data.stratified_sample(items, fraction, int(config["split_seed"]))
        if args.limit:
            items = items[: args.limit]
        todo = [i for i in items if i["id"] not in done]
        # similar prompt lengths in one batch: less padding
        todo.sort(key=lambda i: len(prompt_for(i, base["prompts"])))
        for start in range(0, len(todo), batch_size):
            chunk = todo[start : start + batch_size]
            outputs = generator.run(
                [prompt_for(i, base["prompts"]) for i in chunk],
                mode,
                int(base["generation_seed"]) + start,
            )
            with open(out_path, "a", encoding="utf-8") as handle:
                for item, output in zip(chunk, outputs):
                    _, answer_text = split_reasoning(output["text"])
                    scored = score(item, answer_text, config["equivalence"])
                    cost = stats.CostRecord(
                        seconds=output["batch_seconds"] / len(chunk),
                        prompt_tokens=output["prompt_tokens"],
                        generated_tokens=output["generated_tokens"],
                        model_calls=1,
                        solver_calls=0,
                        peak_vram_bytes=output["peak_vram_bytes"],
                    )
                    record = {
                        "id": item["id"],
                        "bench": bench,
                        "category": item["category"],
                        "mode": args.mode,
                        "extracted": scored["extracted"],  # a letter for multiple choice
                        "correct": scored["correct"],
                        "truncated": output["truncated"],
                        "batch_size": len(chunk),
                        "batch_seconds": output["batch_seconds"],
                        "cost": cost.as_dict(),
                    }
                    handle.write(json.dumps(record) + "\n")
            print(
                f"{bench} {start + len(chunk)}/{len(todo)} {outputs[0]['batch_seconds']:.0f}s",
                flush=True,
            )
    summary = summarise_run(out_path, config, args.mode, batch_size, base["quantization"])
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
    base.add_argument("--summary", default="")
    base.set_defaults(func=cmd_baseline)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
