"""VRAM ceiling of a training or profile run, by device (ADR-023, T211).

The ceiling stays 14.5 GiB (ADR-005 envelope of the 16 GB RTX 5070 Ti) unless the owner sets
`LARIS_VRAM_CEILING_GB` AND the visible GPU has at least `LARGE_CARD_GIB` of memory; even then
the value may not exceed `MAX_FRACTION` of the memory PyTorch sees. A small card can never be
given a higher ceiling, so the exception cannot be used to overrun the 16 GB card.
"""

from __future__ import annotations

import math
import os
from typing import Mapping, Optional

DEFAULT_CEILING_GIB = 14.5
LARGE_CARD_GIB = 24.0
MAX_FRACTION = 0.95
ENV_VAR = "LARIS_VRAM_CEILING_GB"


def resolve_vram_ceiling_gib(requested: Optional[float], total_vram_gib: Optional[float]) -> float:
    """The ceiling to enforce; raises ValueError when `requested` is not allowed on this device."""
    if requested is None:
        return DEFAULT_CEILING_GIB
    if not math.isfinite(requested) or requested <= 0:
        raise ValueError(f"{ENV_VAR} must be a positive number, got {requested}")
    if requested <= DEFAULT_CEILING_GIB:
        return requested  # lowering is always allowed
    if total_vram_gib is None:
        raise ValueError(f"{ENV_VAR} above {DEFAULT_CEILING_GIB} GB needs a visible CUDA device")
    if total_vram_gib < LARGE_CARD_GIB:
        raise ValueError(
            f"{ENV_VAR}={requested} is above the {DEFAULT_CEILING_GIB} GB envelope and this GPU "
            f"has {total_vram_gib:.1f} GB (needs {LARGE_CARD_GIB:.0f} GB or more)"
        )
    if requested > MAX_FRACTION * total_vram_gib:
        raise ValueError(
            f"{ENV_VAR}={requested} exceeds {MAX_FRACTION:.0%} of the {total_vram_gib:.1f} GB "
            "this GPU offers"
        )
    return requested


def vram_ceiling_from_environment(
    total_vram_gib: Optional[float], environ: Optional[Mapping[str, str]] = None
) -> float:
    """`resolve_vram_ceiling_gib` with the value of `LARIS_VRAM_CEILING_GB` (unset: the default)."""
    raw = (environ if environ is not None else os.environ).get(ENV_VAR)
    if raw is None or raw.strip() == "":
        return DEFAULT_CEILING_GIB
    try:
        requested = float(raw)
    except ValueError as exc:
        raise ValueError(f"{ENV_VAR} must be a number, got {raw!r}") from exc
    return resolve_vram_ceiling_gib(requested, total_vram_gib)
