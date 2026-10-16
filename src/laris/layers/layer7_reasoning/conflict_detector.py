"""Compatibility shim for laris.reasoning.conflict_detector (ADR-011)."""

import importlib

_target = importlib.import_module('laris.reasoning.conflict_detector')
for _k, _v in _target.__dict__.items():
    if not _k.startswith('__'):
        globals()[_k] = _v
