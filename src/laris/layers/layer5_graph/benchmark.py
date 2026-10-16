"""Compatibility shim for laris.graph.benchmark (ADR-011)."""

import importlib

_target = importlib.import_module('laris.graph.benchmark')
for _k, _v in _target.__dict__.items():
    if not _k.startswith('__'):
        globals()[_k] = _v
