"""The outcome of one operation and its JSON form.

`status` is `verified` when at least one independent check ran and every check passed; otherwise
the answer is a `proposal` and the caller must not present it as checked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from laris.model.solver.numeric import Check

VERIFIED = "verified"
PROPOSAL = "proposal"


@dataclass
class Outcome:
    answer: Any  # JSON value: a string, a list, an object
    text: str  # the answer as one line
    checks: List[Check] = field(default_factory=list)
    latex: Optional[str] = None
    numeric: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    sources: List[Dict[str, str]] = field(default_factory=list)

    @property
    def status(self) -> str:
        return VERIFIED if self.checks and all(c.passed for c in self.checks) else PROPOSAL

    def to_dict(self, operation: str, engine: Dict[str, str]) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "operation": operation,
            "status": self.status,
            "answer": self.answer,
            "text": self.text,
            "checks": [c.to_dict() for c in self.checks],
            "engine": engine,
        }
        if self.latex is not None:
            out["latex"] = self.latex
        if self.numeric is not None:
            out["numeric"] = self.numeric
        if self.notes:
            out["notes"] = list(self.notes)
        if self.sources:
            out["sources"] = list(self.sources)
        return out


def show(expr) -> str:
    """SymPy's plain string, with `**` written as `^`."""
    return str(expr).replace("**", "^")


def latex(expr) -> str:
    import sympy

    return sympy.latex(expr)


def numeric_text(expr, settings) -> Optional[str]:
    """The value to `output_digits` significant digits, or None when it is not a finite number."""
    import sympy

    if getattr(expr, "free_symbols", None) or not getattr(expr, "is_number", False):
        return None
    try:
        number = sympy.N(expr, settings.output_digits)
    except Exception:
        return None
    if number.has(sympy.oo, -sympy.oo, sympy.zoo, sympy.nan):
        return None
    return str(number)
