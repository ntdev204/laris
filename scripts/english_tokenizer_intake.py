#!/usr/bin/env python3
"""Intake check of the owner-fitted English tokenizer (runbook section 9.2, step 1). Read-only: fits nothing.

Checks the vocabulary size and the special-token ids against the contract written by the fit, then measures
fertility (tokens per whitespace word) and the unknown-token rate on the validation split of every MLM source, with
the same normalisation as the fit corpus. Exit 1 when the general-text fertility is above the gate (default 1.35) or
a check fails. Tokenizer inference only; the validation split is used, never the test split.

Usage: python scripts/english_tokenizer_intake.py --model artifacts/tokenizer/english-r1-56k-nd/laris_spm_en_56k_nd.model
"""

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pyarrow.parquet as pq
import sentencepiece as spm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from laris.shared.language.tokenization.normalized import normalize_for_tokenizer  # noqa: E402

GENERAL = [
    "wikipedia_en", "fineweb_edu_en", "openwebtext_en", "c4_en", "gutenberg_en", "cc_news_en",
    "cnn_dailymail_en", "xsum_en", "wikipedia_simple_en",
]  # fmt: skip
STEM = ["arxiv_fulltext", "pubmed_fulltext", "open_web_math", "uspto_patents"]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--contract", type=Path, help="default: <model stem>_contract.json")
    parser.add_argument("--processed", type=Path, default=ROOT / "data/processed")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--passages", type=int, default=1500, help="per source")
    parser.add_argument("--gate", type=float, default=1.35)
    args = parser.parse_args(argv)
    contract_path = args.contract or args.model.with_name(args.model.stem + "_contract.json")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    processor = spm.SentencePieceProcessor(model_file=str(args.model))
    special = {t: processor.piece_to_id(t) for t in contract["special_tokens"]}
    sources = GENERAL + STEM + sorted(
        p.parent.name for p in args.processed.glob("se_*/val.parquet")
    )
    rng = random.Random(0)
    report: Dict[str, Any] = {
        "model_sha256": hashlib.sha256(args.model.read_bytes()).hexdigest(),
        "vocab_size": processor.get_piece_size(),
        "contract_vocab_size": contract["vocab_size"],
        "special_ids": special,
        "special_ids_match_contract": special == contract["special_tokens"],
        "sources": {},
    }
    totals: Dict[str, List[int]] = {}
    for source in sources:
        texts = pq.read_table(args.processed / source / "val.parquet", columns=["text"])
        texts = texts.column(0).to_pylist()
        rng.shuffle(texts)
        tokens = words = unknown = 0
        for text in texts[: args.passages]:
            text = normalize_for_tokenizer(text)
            ids = processor.encode(text, out_type=int)
            tokens += len(ids)
            words += len(text.split())
            unknown += ids.count(processor.unk_id())
        report["sources"][source] = {
            "words": words,
            "fertility": round(tokens / words, 4),
            "unk_rate": unknown / tokens,
        }
        group = "general" if source in GENERAL else "stem"
        total = totals.setdefault(group, [0, 0, 0])
        total[0], total[1], total[2] = total[0] + tokens, total[1] + words, total[2] + unknown
    report["groups"] = {
        g: {"fertility": round(t[0] / t[1], 4), "unk_rate": t[2] / t[0]} for g, t in totals.items()
    }
    ok = (
        report["vocab_size"] == report["contract_vocab_size"]
        and report["special_ids_match_contract"]
        and report["groups"]["general"]["fertility"] <= args.gate
    )
    report["gate"] = args.gate
    report["passed"] = ok
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for name, row in report["sources"].items():
        print(f"{name:28s} fertility {row['fertility']:.3f}  unk {row['unk_rate']:.2e}")
    print(json.dumps({k: report[k] for k in ("vocab_size", "special_ids_match_contract", "groups", "passed")}))
    print("[PASS] intake" if ok else "[FAIL] intake: do not continue to step 2")
    print("Validation split only; held-out fertility (G10) is measured once at T100.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
