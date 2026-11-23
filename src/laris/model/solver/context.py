"""What an operation receives: its arguments, the settings, a parser and the constants table."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from laris.model.solver.errors import SolverError
from laris.model.solver.expr import Parser
from laris.model.solver.settings import SolverSettings


@dataclass
class Context:
    args: Dict[str, Any]
    settings: SolverSettings
    parser: Parser
    sources: List[Dict[str, str]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def assume(self) -> str:
        return self.parser.assume

    def text(self, key: str, required: bool = True) -> Optional[str]:
        value = self.args.get(key)
        if value is None and not required:
            return None
        if not isinstance(value, str) or not value.strip():
            raise SolverError("invalid_arguments", f"{key} must be a non-empty string")
        if len(value) > self.settings.max_expression_chars:
            raise SolverError("input_too_large", f"{key} is too long")
        return value

    def require(self, key: str) -> Any:
        if key not in self.args or self.args[key] is None:
            raise SolverError("invalid_arguments", f"this operation needs {key}")
        return self.args[key]

    def items(self, key: str) -> List[Any]:
        value = self.require(key)
        if not isinstance(value, list) or not value:
            raise SolverError("invalid_arguments", f"{key} must be a non-empty list")
        if len(value) > self.settings.max_items:
            raise SolverError(
                "input_too_large", f"{key} holds more than {self.settings.max_items} items"
            )
        return value

    def expression(self, key: str = "expression"):
        return self.parser.expression(self.require(key), key)

    def variable(self, expressions: List[Any], key: str = "variable"):
        """The variable named by `key`, or the only free symbol of `expressions`."""
        name = self.args.get(key)
        if name is not None:
            return self.parser.symbol(name)
        free = set()
        for e in expressions:
            free |= e.free_symbols
        if len(free) != 1:
            raise SolverError(
                "invalid_arguments", f"name the {key}: the expression has {len(free)} variables"
            )
        return next(iter(free))

    def substitutions(self) -> Dict[Any, Any]:
        """`substitutions` as symbol -> exact value; a value may be `{"constant": name}`."""
        raw = self.args.get("substitutions")
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            raise SolverError("invalid_arguments", "substitutions must be an object")
        if len(raw) > self.settings.max_items:
            raise SolverError("input_too_large", "substitutions holds too many names")
        out = {}
        for name, given in raw.items():
            symbol = self.parser.symbol(name)
            if isinstance(given, dict):
                if set(given) != {"constant"}:
                    raise SolverError(
                        "invalid_arguments", "a substitution object holds only constant"
                    )
                from laris.model.solver.constants import table

                entry = table(self.settings).lookup(given["constant"])
                out[symbol] = entry.exact_value()
                self.notes.append(
                    f"{name} = {entry.name} ({entry.unit or 'dimensionless'}), "
                    f"CODATA {entry.release}"
                )
                source = entry.source()
                if source not in self.sources:
                    self.sources.append(source)
            else:
                out[symbol] = self.parser.number(given, f"substitutions.{name}")
        return out
