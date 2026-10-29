"""`laris infer <task>`: single-example predictions from a trained checkpoint."""

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Dict

import numpy as np

from laris.language.inference.loader import load_encoder
from laris.language.inference.predictor import LanguageEncoderPredictor


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--checkpoint", required=True, help="Checkpoint dir (e.g. <run>/best)")
    parser.add_argument("--tokenizer-model", required=True, help="SentencePiece .model file")
    parser.add_argument("--device", default=None, help="cuda or cpu (default: auto)")


class _InferCommand:
    """Adapts one prediction task to the `add_arguments` / `run` command contract."""

    def __init__(
        self,
        flags: Dict[str, Dict[str, Any]],
        call: Callable[[LanguageEncoderPredictor, argparse.Namespace], Any],
    ) -> None:
        self.flags = flags
        self.call = call

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _common(parser)
        for name, kwargs in self.flags.items():
            parser.add_argument(name, **kwargs)

    def run(self, args: argparse.Namespace) -> int:
        try:
            encoder = load_encoder(
                Path(args.checkpoint), Path(args.tokenizer_model), device=args.device
            )
            result = self.call(LanguageEncoderPredictor(encoder), args)
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            print(f"[ERROR] {exc}")
            return 2
        if isinstance(result, np.ndarray):
            print(f"embeddings shape={result.shape}")
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0


def _embed(predictor: LanguageEncoderPredictor, args: argparse.Namespace) -> Any:
    if args.text:
        texts = list(args.text)
    else:
        texts = [t for t in Path(args.input).read_text(encoding="utf-8").splitlines() if t.strip()]
    vectors = predictor.embed(texts)
    if args.output:
        np.save(args.output, vectors)
        print(f"saved {args.output}")
    return vectors


_REQUIRED = {"required": True}
COMMANDS: Dict[str, Any] = {
    "fill-mask": _InferCommand(
        {
            "--text": {"required": True, "help": "Text containing one or more literal [MASK]"},
            "--top-k": {"type": int, "default": 5},
        },
        lambda p, a: p.fill_mask(a.text, top_k=a.top_k),
    ),
    "nli": _InferCommand(
        {"--premise": _REQUIRED, "--hypothesis": _REQUIRED},
        lambda p, a: p.nli(a.premise, a.hypothesis),
    ),
    "paraphrase": _InferCommand(
        {"--a": _REQUIRED, "--b": _REQUIRED}, lambda p, a: p.paraphrase(a.a, a.b)
    ),
    "similarity": _InferCommand(
        {"--a": _REQUIRED, "--b": _REQUIRED}, lambda p, a: p.similarity(a.a, a.b)
    ),
    "qa": _InferCommand(
        {"--context": _REQUIRED, "--question": _REQUIRED},
        lambda p, a: p.qa(a.context, a.question),
    ),
    "embed": _InferCommand(
        {
            "--text": {"nargs": "+", "help": "One or more texts"},
            "--input": {"help": "Text file with one text per line"},
            "--output": {"help": "Write embeddings to this .npy file"},
        },
        _embed,
    ),
}
