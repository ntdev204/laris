"""Compatibility shim for laris.orchestration.dag_validator (ADR-011)."""

import importlib

_target = importlib.import_module('laris.orchestration.dag_validator')
for _k, _v in _target.__dict__.items():
    if not _k.startswith('__'):
        globals()[_k] = _v
