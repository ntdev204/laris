"""Compatibility shim for laris.retrieval.fusion (ADR-011)."""

import importlib

_target = importlib.import_module('laris.retrieval.fusion')
for _k, _v in _target.__dict__.items():
    if not _k.startswith('__'):
        globals()[_k] = _v
