"""Shared CLI helpers: resolve configuration once and build services from it.

Command-line flags are the highest-precedence configuration tier. They default to None so the
value then comes from `configs/default.yaml`, project and user YAML, or `LARIS_*` environment.
"""

import argparse
from pathlib import Path
from typing import Any, Dict, Optional

from laris.client.application.service import SearchService
from laris.client.application.workspace import Workspace
from laris.client.learning.hooks import make_ingest_hook
from laris.shared.harness.runtime import HarnessRuntime


def model_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--checkpoint", help="Local checkpoint for dense search and QA tools")
    parser.add_argument("--tokenizer-model", help="SentencePiece .model for the checkpoint")
    parser.add_argument("--device", default=None, help="cuda or cpu (default: auto)")


def cli_overrides(args: argparse.Namespace) -> Dict[str, Any]:
    """Map flags that were given to configuration keys (dotted names)."""
    mapping = {
        "model_api_url": "model_api.base_url",
        "model_name": "model_api.model",
        "api_key_env": "model_api.api_key_env",
        "workspace": "app.workspace",
        "chat_dir": "app.chat_dir",
        "host": None,
        "port": None,
    }
    out: Dict[str, Any] = {}
    for flag, key in mapping.items():
        value = getattr(args, flag, None)
        if key and value is not None:
            out[key] = value
    if getattr(args, "allow_write", False):
        out["agent.approval.mode"] = "auto"
    return out


def load_runtime(args: Optional[argparse.Namespace] = None) -> HarnessRuntime:
    return HarnessRuntime.load(Path.cwd(), cli_overrides(args) if args else None)


def make_service(args: argparse.Namespace, runtime: HarnessRuntime) -> SearchService:
    cfg = runtime.config.app
    service = SearchService(
        Workspace(Path(cfg.workspace)),
        Path(args.checkpoint) if getattr(args, "checkpoint", None) else None,
        Path(args.tokenizer_model) if getattr(args, "tokenizer_model", None) else None,
        getattr(args, "device", None),
        notice=runtime.strings.get("service.qualification_notice"),
        rrf_k=cfg.rrf_k,
        max_top_k=cfg.search_max_top_k,
    )
    service.on_ingest = make_ingest_hook(lambda: runtime)
    return service
