"""Compatibility shim for laris.reasoning.adversarial_evaluation (ADR-011)."""

import importlib

_target = importlib.import_module('laris.reasoning.adversarial_evaluation')
for _k, _v in _target.__dict__.items():
    if not _k.startswith('__'):
        globals()[_k] = _v
