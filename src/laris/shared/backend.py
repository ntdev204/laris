"""Load a generation backend: `package.module:ClassName` or the scripted placeholder."""

import importlib
from pathlib import Path
from typing import Any, Optional

from laris.protocol import ChatProvider
from laris.shared.harness.strings import StringCatalogue
from laris.shared.offline import OfflinePlanner

PUBLIC_STRINGS = Path(__file__).resolve().parent / "harness" / "public_strings.yaml"


def load_backend(spec: Optional[str], strings: Any = None) -> ChatProvider:
    """`package.module:ClassName` (zero-argument constructor) or the offline placeholder."""
    if not spec:
        return OfflinePlanner(strings or StringCatalogue.load(PUBLIC_STRINGS))
    module_name, _, class_name = spec.partition(":")
    if not class_name:
        raise ValueError("--backend must look like package.module:ClassName")
    backend = getattr(importlib.import_module(module_name), class_name)()
    if not isinstance(backend, ChatProvider):
        raise TypeError(f"{spec} is not a ChatProvider")
    return backend
