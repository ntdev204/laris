"""T211: the VRAM ceiling is 14.5 GB by default and rises only on a 24 GB+ GPU (ADR-023)."""

import pytest

from laris.research.language.training.vram_ceiling import (
    DEFAULT_CEILING_GIB,
    ENV_VAR,
    resolve_vram_ceiling_gib,
    vram_ceiling_from_environment,
)

A100 = 39.5  # GiB visible to PyTorch on an A100 40GB
RTX_5070_TI = 15.47


def test_default_is_the_adr_005_envelope() -> None:
    assert resolve_vram_ceiling_gib(None, RTX_5070_TI) == DEFAULT_CEILING_GIB == 14.5
    assert vram_ceiling_from_environment(RTX_5070_TI, {}) == 14.5
    assert vram_ceiling_from_environment(None, {ENV_VAR: "  "}) == 14.5


def test_lowering_is_always_allowed() -> None:
    assert resolve_vram_ceiling_gib(11.5, RTX_5070_TI) == 11.5
    assert vram_ceiling_from_environment(None, {ENV_VAR: "12"}) == 12.0


def test_small_card_can_never_exceed_the_envelope() -> None:
    for request in (14.6, 16.0, 24.0):
        with pytest.raises(ValueError, match="needs 24 GB or more"):
            resolve_vram_ceiling_gib(request, RTX_5070_TI)
    with pytest.raises(ValueError):
        vram_ceiling_from_environment(RTX_5070_TI, {ENV_VAR: "36"})


def test_large_card_allows_up_to_95_percent() -> None:
    assert resolve_vram_ceiling_gib(36.0, A100) == 36.0
    assert resolve_vram_ceiling_gib(A100 * 0.95, A100) == pytest.approx(A100 * 0.95)
    with pytest.raises(ValueError, match="exceeds 95%"):
        resolve_vram_ceiling_gib(39.0, A100)


def test_raising_needs_a_visible_cuda_device() -> None:
    with pytest.raises(ValueError, match="visible CUDA device"):
        resolve_vram_ceiling_gib(20.0, None)


@pytest.mark.parametrize("bad", ["abc", "nan", "inf", "-1", "0"])
def test_bad_values_are_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        vram_ceiling_from_environment(A100, {ENV_VAR: bad})
