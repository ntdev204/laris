"""Compatibility shim for laris.scientific.schemas (ADR-011)."""

import importlib

_target = importlib.import_module('laris.scientific.schemas')
for _k, _v in _target.__dict__.items():
    if not _k.startswith('__'):
        globals()[_k] = _v
