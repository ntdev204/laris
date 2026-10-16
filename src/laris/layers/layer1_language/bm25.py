"""Compatibility shim for laris.language.bm25 (ADR-011)."""

import importlib

_target = importlib.import_module('laris.language.bm25')
for _k, _v in _target.__dict__.items():
    if not _k.startswith('__'):
        globals()[_k] = _v
