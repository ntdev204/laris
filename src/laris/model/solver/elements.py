"""Standard atomic weights from CIAAW (IUPAC), abridged, for molar masses (T276 follow-up).

The packaged table is `data/ciaaw-abridged-atomic-weights.tsv`, extracted by
`scripts/extract_atomic_weights.py` from https://www.ciaaw.org/abridged-atomic-weights.htm
(Abridged Standard Atomic Weights 2024, based on Atomic Weights 2021 with the 2024 revisions of
Gd, Lu and Zr; owner approval 2026-11-23). The loader refuses a file whose SHA-256 differs from
`SolverSettings.atomic_weights_sha256`. An element without a standard atomic weight (no stable
isotope, e.g. Tc) has none here, and a formula holding it has no molar mass.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

from laris.model.solver.errors import SolverError
from laris.model.solver.settings import SolverSettings

PACKAGED = Path(__file__).with_name("data") / "ciaaw-abridged-atomic-weights.tsv"


@dataclass(frozen=True)
class Weight:
    symbol: str
    value: str  # g/mol, as printed
    uncertainty: str


@dataclass(frozen=True)
class WeightTable:
    weights: Dict[str, Weight]
    release: str
    url: str
    sha256: str

    def get(self, symbol: str) -> Weight:
        found = self.weights.get(symbol)
        if found is None:
            raise SolverError("rejected", f"{symbol} has no standard atomic weight")
        return found

    def source(self) -> Dict[str, str]:
        return {"name": self.release, "url": self.url, "sha256": self.sha256}


def parse(text: str, sha256: str) -> WeightTable:
    release, url = "", ""
    weights: Dict[str, Weight] = {}
    for line in text.splitlines():
        if line.startswith("# CIAAW"):
            release = line[2:].split(" (")[0]
        elif line.startswith("# source:"):
            url = line.split(":", 1)[1].strip()
        elif line and not line.startswith("#"):
            z, symbol, _, value, uncertainty, _ = (line.split("\t") + [""] * 6)[:6]
            if value:
                weights[symbol] = Weight(symbol, value, uncertainty)
    if not release or not weights:
        raise SolverError("rejected", "the atomic weights table names no release")
    return WeightTable(weights, release, url, sha256)


_CACHE: Dict[Tuple[str, str], WeightTable] = {}


def table(settings: SolverSettings) -> WeightTable:
    path = (
        Path(settings.atomic_weights_file).expanduser()
        if settings.atomic_weights_file
        else PACKAGED
    )
    key = (str(path), settings.atomic_weights_sha256)
    if key not in _CACHE:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != settings.atomic_weights_sha256:
            raise SolverError(
                "rejected", "the atomic weights table does not match its pinned SHA-256"
            )
        _CACHE[key] = parse(raw.decode("utf-8"), digest)
    return _CACHE[key]
