"""CODATA fundamental physical constants from NIST's ASCII table (T276).

The packaged table is the 2022 CODATA adjustment as NIST publishes it
(https://physics.nist.gov/cuu/Constants/Table/allascii.txt, last modified 2024-05-07, downloaded
2026-11-23, SHA-256 in `SolverSettings.codata_sha256`). The loader refuses a table whose hash
differs, so a lookup is checked by provenance: the value is the published one, byte for byte.

A value NIST prints with `...` is exact by definition but truncated in the table; it is returned
with `truncated: true`, and `exact_value()` gives the printed digits, not the exact number.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from laris.model.solver.errors import SolverError
from laris.model.solver.numeric import Check
from laris.model.solver.result import Outcome
from laris.model.solver.settings import SolverSettings

PACKAGED = Path(__file__).with_name("data") / "codata-2022-allascii.txt"
URL = "https://physics.nist.gov/cuu/Constants/Table/allascii.txt"
NAME_END, VALUE_END, UNCERTAINTY_END = 60, 85, 110

# common symbols -> the NIST name
ALIASES: Dict[str, str] = {
    "c": "speed of light in vacuum",
    "h": "Planck constant",
    "hbar": "reduced Planck constant",
    "e": "elementary charge",
    "k": "Boltzmann constant",
    "k_B": "Boltzmann constant",
    "N_A": "Avogadro constant",
    "R": "molar gas constant",
    "F": "Faraday constant",
    "G": "Newtonian constant of gravitation",
    "g_n": "standard acceleration of gravity",
    "m_e": "electron mass",
    "m_p": "proton mass",
    "m_n": "neutron mass",
    "m_u": "atomic mass constant",
    "u": "atomic mass constant",
    "epsilon_0": "vacuum electric permittivity",
    "mu_0": "vacuum mag. permeability",
    "sigma": "Stefan-Boltzmann constant",
    "alpha": "fine-structure constant",
    "a_0": "Bohr radius",
    "R_inf": "Rydberg constant",
    "atm": "standard atmosphere",
    "eV": "electron volt",
    "mu_B": "Bohr magneton",
    "b": "Wien wavelength displacement law constant",
}


@dataclass(frozen=True)
class Constant:
    name: str
    value: str  # as printed, spaces removed
    uncertainty: Optional[str]  # None when exact
    unit: str
    truncated: bool
    release: str
    sha256: str

    @property
    def exact(self) -> bool:
        return self.uncertainty is None

    def exact_value(self):
        import sympy

        return sympy.Rational(self.value)

    def source(self) -> Dict[str, str]:
        return {"name": f"CODATA {self.release} (NIST)", "url": URL, "sha256": self.sha256}

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "value": self.value,
            "uncertainty": self.uncertainty,
            "unit": self.unit,
            "exact": self.exact,
            "truncated": self.truncated,
            "release": self.release,
        }


def _number(field: str) -> Tuple[str, bool]:
    text = field.strip()
    truncated = "..." in text
    text = text.replace("...", "").replace(" ", "")
    text = re.sub(r"e([+-]?\d+)$", r"e\1", text)
    return text, truncated


class Table:
    def __init__(self, constants: List[Constant], release: str, sha256: str) -> None:
        self.release, self.sha256 = release, sha256
        self.by_name = {c.name.casefold(): c for c in constants}

    def lookup(self, query: object) -> Constant:
        if not isinstance(query, str) or not query.strip() or len(query) > 200:
            raise SolverError("invalid_arguments", "constant must be a name")
        key = ALIASES.get(query.strip(), query.strip())
        found = self.by_name.get(key.casefold())
        if found is not None:
            return found
        words = key.casefold().split()
        matches = [c for k, c in self.by_name.items() if all(w in k for w in words)]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise SolverError("rejected", "no CODATA constant has that name")
        names = sorted(c.name for c in matches)[:8]
        raise SolverError("rejected", "the name matches several constants: " + "; ".join(names))


def parse(text: str, sha256: str) -> Table:
    lines = text.splitlines()
    release_match = re.search(r"(\d{4}) CODATA adjustment", text)
    if not release_match:
        raise SolverError("rejected", "the constants table names no CODATA adjustment")
    release = release_match.group(1)
    start = next((i for i, line in enumerate(lines) if line.startswith("-----")), None)
    if start is None:
        raise SolverError("rejected", "the constants table has no header rule")
    constants = []
    for line in lines[start + 1 :]:
        if not line.strip():
            continue
        name = line[:NAME_END].strip()
        value, truncated = _number(line[NAME_END:VALUE_END])
        raw_uncertainty = line[VALUE_END:UNCERTAINTY_END].strip()
        uncertainty = None if raw_uncertainty == "(exact)" else _number(raw_uncertainty)[0]
        unit = line[UNCERTAINTY_END:].strip()
        constants.append(Constant(name, value, uncertainty, unit, truncated, release, sha256))
    return Table(constants, release, sha256)


_CACHE: Dict[Tuple[str, str], Table] = {}


def table(settings: SolverSettings) -> Table:
    path = Path(settings.codata_file).expanduser() if settings.codata_file else PACKAGED
    key = (str(path), settings.codata_sha256)
    if key not in _CACHE:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != settings.codata_sha256:
            raise SolverError("rejected", "the constants table does not match its pinned SHA-256")
        _CACHE[key] = parse(raw.decode("utf-8"), digest)
    return _CACHE[key]


def constant(ctx) -> Outcome:
    entry = table(ctx.settings).lookup(ctx.require("constant"))
    text = f"{entry.name} = {entry.value}" + (f" {entry.unit}" if entry.unit else "")
    text += " (exact)" if entry.exact else f" +- {entry.uncertainty}"
    out = Outcome(
        entry.to_dict(), text, [Check("table SHA-256 matches the pinned CODATA release", True)]
    )
    out.sources.append(entry.source())
    if entry.truncated:
        out.notes.append("the value is exact by definition; NIST prints it truncated")
    return out
