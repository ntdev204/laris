"""Compatibility shim for laris.orchestration.cycle_detector (ADR-011)."""

import importlib

_target = importlib.import_module('laris.orchestration.cycle_detector')
for _k, _v in _target.__dict__.items():
    if not _k.startswith('__'):
        globals()[_k] = _v
