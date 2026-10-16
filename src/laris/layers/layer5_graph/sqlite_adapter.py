"""Compatibility shim for laris.graph.sqlite_adapter (ADR-011)."""

import importlib

_target = importlib.import_module('laris.graph.sqlite_adapter')
for _k, _v in _target.__dict__.items():
    if not _k.startswith('__'):
        globals()[_k] = _v
