"""What one solver call may use and how its results are checked (T276).

Every value comes from the `model_service` configuration (`solver_*` keys); the defaults below are
the ones `configs/default.yaml` states, so a test can build the settings without a file.
"""

from dataclasses import dataclass
from typing import Any

CODATA_2022_SHA256 = "77fb90e66c40db3e6eb16630bc9c88e4c7c8beddbe5e71be406f2f26e3f67e67"


@dataclass(frozen=True)
class SolverSettings:
    timeout_s: float = 10.0  # wall clock of one call; the worker process is killed after it
    memory_bytes: int = 2 * 1024**3  # address-space ceiling of the worker process (0: none)
    isolate: bool = True  # run each call in a forked worker (False: in the caller, tests only)
    max_expression_chars: int = 4000  # longest expression, unit or reaction text
    max_nodes: int = 2000  # most syntax nodes in one expression
    max_integer_digits: int = 1000  # longest integer, as input or as a computed power
    max_exponent: int = 10000  # largest constant integer exponent or factorial argument
    max_matrix_size: int = 12  # most rows or columns of a matrix
    max_items: int = 64  # most equations, integers, species or substitutions
    max_sum_terms: int = 100000  # a finite sum longer than this is checked numerically only
    max_result_chars: int = 20000  # a longer answer is refused
    working_digits: int = 50  # mpmath precision of the numeric checks
    output_digits: int = 15  # significant digits of the reported numeric value
    check_points: int = 6  # random points of an identity or residual check
    check_seed: int = 276  # seed of those points
    check_tolerance: float = 1e-20  # relative tolerance of exact checks at working precision
    limit_tolerance: float = 1e-6  # relative tolerance of the numeric limit check
    quad_tolerance: float = 1e-15  # relative tolerance against numeric integration or summation
    unit_tolerance: float = 1e-8  # relative tolerance between the two unit conversion routes
    codata_file: str = ""  # NIST CODATA ASCII table; empty selects the packaged 2022 table
    codata_sha256: str = CODATA_2022_SHA256  # the table is refused when its hash differs

    @classmethod
    def from_config(cls, cfg: Any) -> "SolverSettings":
        """The settings from a `ModelServiceConfig` (its `solver_*` fields)."""
        values = {}
        for name in cls.__dataclass_fields__:
            key = f"solver_{name}"
            if hasattr(cfg, key):
                values[name] = getattr(cfg, key)
        return cls(**values)
