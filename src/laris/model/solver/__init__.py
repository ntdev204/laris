"""Deterministic STEM solver of the model block (T276, ADR-026): structured problems answered
without a model, every answer re-checked by an independent route or marked a proposal.

Domains: algebra, calculus, linear algebra, number theory, units and dimensions, CODATA 2022
constants (NIST), stoichiometry. `run` is the isolated entry point the tool route uses; `solve`
computes in the caller's process. SymPy 1.14.0 and its dependency mpmath 1.3.0 (owner approval
2026-11-23).
"""

from laris.model.solver.engine import OPERATIONS, solve
from laris.model.solver.errors import SolverError
from laris.model.solver.runner import run
from laris.model.solver.settings import SolverSettings

__all__ = ["OPERATIONS", "SolverError", "SolverSettings", "run", "solve"]
