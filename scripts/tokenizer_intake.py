#!/usr/bin/env python3
"""Intake check of an owner-fitted tokenizer candidate (T97, SR-M5). Read-only: fits nothing.

Verifies, against the candidate report, (1) file SHA-256 values of the model, vocabulary,
contract, development sample and fit corpus, (2) the vocabulary size and that the contract
agrees with the model piece by piece, (3) that the eight special tokens keep the ids of the
previous contract, and (4) fertility and unknown-token rate on the locked development sample,
recomputed and compared with the reported numbers. Exit 0 only when every check passes.
Tokenizer inference only; no model is loaded and nothing is trained or fitted.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
TOLERANCE = 1e-6
GATE = 1.35


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def measure(processor: Any, development: Dict[str, List[str]]) -> Dict[str, Dict[str, float]]:
    unk = processor.unk_id()
    result: Dict[str, Dict[str, float]] = {}
    for source, texts in development.items():
        tokens = words = unks = 0
        for text in texts:
            ids = processor.encode(text, out_type=int)
            n_words = len(text.split())
            tokens += len(ids)
            words += n_words
            unks += sum(1 for i in ids if i == unk)
        result[source] = {
            "tokens": tokens,
            "unk": unks,
            "unk_rate": unks / tokens if tokens else 0.0,
            "fertility": tokens / words if words else 0.0,
        }
    return result


def macro_by_language(measured: Dict[str, Dict[str, float]]) -> Dict[str, float]:
    groups: Dict[str, List[float]] = {}
    for source, row in measured.items():
        groups.setdefault(source.split("/")[0], []).append(row["fertility"])
    return {lang: sum(v) / len(v) for lang, v in groups.items()}


def check(report_path: Path, old_contract_path: Path, root: Path = ROOT) -> List[str]:
    import sentencepiece as spm

    report = json.loads(report_path.read_text(encoding="utf-8"))
    sel = report["selected_candidate"]
    model_path = root / sel["model"]
    problems: List[str] = []

    def expect(ok: bool, message: str) -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {message}")
        if not ok:
            problems.append(message)

    contract_path = model_path.with_name(model_path.stem + "_contract.json")
    vocab_path = model_path.with_suffix(".vocab")
    expect(sha256_file(model_path) == sel["model_sha256"], "model SHA-256 matches the report")
    expect(sha256_file(vocab_path) == sel["vocab_sha256"], "vocabulary SHA-256 matches the report")
    expect(
        sha256_file(contract_path) == sel["contract_sha256"], "contract SHA-256 matches the report"
    )
    dev_path = root / report["development_sample"]["path"]
    expect(
        sha256_file(dev_path) == report["development_sample"]["sha256"],
        "development sample SHA-256",
    )
    fit_corpus = model_path.parent.parent / "fit-actual.txt"
    if fit_corpus.is_file():
        expect(
            sha256_file(fit_corpus) == sel["fit"]["corpus_sha256"],
            "fit corpus SHA-256 matches the report",
        )
    else:
        expect(False, f"fit corpus {fit_corpus.name} is present")

    processor = spm.SentencePieceProcessor(model_file=str(model_path))
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    old = json.loads(old_contract_path.read_text(encoding="utf-8"))
    size = processor.get_piece_size()
    expect(
        size == contract["vocab_size"] == len(contract["token_to_id"]),
        f"vocabulary size {size} agrees",
    )
    mismatches = [
        p for p, i in contract["token_to_id"].items() if i >= size or processor.id_to_piece(i) != p
    ]
    expect(
        not mismatches, f"contract equals the model piece by piece ({len(mismatches)} differences)"
    )
    expect(
        contract["special_tokens"] == old["special_tokens"],
        "special-token ids equal the previous contract",
    )
    expect(
        all(processor.piece_to_id(t) == i for t, i in old["special_tokens"].items()),
        "special tokens resolve to their ids in the model",
    )
    development = json.loads(dev_path.read_text(encoding="utf-8"))
    measured = measure(processor, development)
    for source, row in measured.items():
        reported = sel["unk_on_development_sample"][source]
        expect(
            row["tokens"] == reported["tokens"] and row["unk"] == reported["unk"],
            f"token and unknown counts on {source} match the report",
        )
    macro = macro_by_language(measured)
    for lang, value in macro.items():
        reported_macro = sel["development_macro_fertility"][lang]
        expect(
            abs(value - reported_macro) < TOLERANCE, f"{lang} macro fertility {value:.4f} matches"
        )
        expect(
            value <= GATE, f"{lang} macro fertility {value:.4f} <= {GATE} on the development sample"
        )
    return problems


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--report", type=Path, default=ROOT / "reports/tokenizer/foundation-r1-candidates.json"
    )
    parser.add_argument(
        "--previous-contract",
        type=Path,
        default=ROOT / "artifacts/tokenizer/laris_spm_32k_contract.json",
    )
    args = parser.parse_args(argv)
    problems = check(args.report, args.previous_contract)
    print("\n[FAIL] intake" if problems else "\n[PASS] intake: the candidate matches its report")
    print("Development sample only; held-out fertility (G10, G11) is measured once at T100.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
