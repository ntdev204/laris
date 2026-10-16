"""Compatibility shim for laris.language.stem_benchmark (ADR-011)."""

import importlib

_target = importlib.import_module('laris.language.stem_benchmark')
for _k, _v in _target.__dict__.items():
    if not _k.startswith('__'):
        globals()[_k] = _v
