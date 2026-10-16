"""Unit tests for STEM Unit Normalization and Epistemic Assertion Classification.

Module ID: MOD-SCINLP-003 (Boundary D: Scientific Language Intelligence)
Subtask: M4-SCINLP-003-SUB-01 (Issue #58)
Parent Task: #26
Tests:
- Quantity parsing and SI canonical base normalization with zero precision loss
- Dimensional vector compatibility and conversion across compatible units
- Incompatible unit conversion error handling
- Epistemic classification into empirical, correlational, causal, and speculative
- Anti-overreach guardrail: strict prevention of correlation-to-causation promotion
- Quantity extraction from running scientific text with evidence coordinates
- Serialization and roundtrip consistency
"""

import json
import math

import pytest

from laris.core.errors import (
    EpistemicOverreachError,
    ModuleContractViolationError,
    UnitConversionError,
)
from laris.scientific import (
    DimensionalVector,
    EpistemicAssertionType,
    STEMUnitNormalizer,
)


def test_stem_unit_normalizer_length_units():
    """Verify length normalization across orders of magnitude to canonical meter (m)."""
    normalizer = STEMUnitNormalizer()

    # nm to m
    q_nm = normalizer.normalize_quantity("500 nm")
    assert q_nm.canonical_unit == "m"
    assert math.isclose(q_nm.canonical_value, 5e-7, rel_tol=1e-9)

    # µm to m
    q_um = normalizer.normalize_quantity("4.2 µm")
    assert math.isclose(q_um.canonical_value, 4.2e-6, rel_tol=1e-9)

    # Å (angstrom) to m
    q_ang = normalizer.normalize_quantity("1.54 Å")
    assert math.isclose(q_ang.canonical_value, 1.54e-10, rel_tol=1e-9)

    # km to m
    q_km = normalizer.normalize_quantity("12.5 km")
    assert math.isclose(q_km.canonical_value, 12500.0, rel_tol=1e-9)


def test_stem_unit_normalizer_mass_units():
    """Verify mass normalization across units to canonical kilogram (kg)."""
    normalizer = STEMUnitNormalizer()

    # grams to kg
    q_g = normalizer.normalize_quantity("250 g")
    assert q_g.canonical_unit == "kg"
    assert math.isclose(q_g.canonical_value, 0.25, rel_tol=1e-9)

    # mg to kg
    q_mg = normalizer.normalize_quantity("15 mg")
    assert math.isclose(q_mg.canonical_value, 1.5e-5, rel_tol=1e-9)

    # kDa to kg
    q_kda = normalizer.normalize_quantity("65 kDa")
    assert math.isclose(q_kda.canonical_value, 65 * 1.66053906660e-24, rel_tol=1e-9)


def test_stem_unit_normalizer_time_and_frequency():
    """Verify time (s) and frequency (Hz) normalization."""
    normalizer = STEMUnitNormalizer()

    # ms to s
    q_ms = normalizer.normalize_quantity("250 ms")
    assert q_ms.canonical_unit == "s"
    assert math.isclose(q_ms.canonical_value, 0.25, rel_tol=1e-9)

    # min to s
    q_min = normalizer.normalize_quantity("30 min")
    assert math.isclose(q_min.canonical_value, 1800.0, rel_tol=1e-9)

    # GHz to Hz
    q_ghz = normalizer.normalize_quantity("2.4 GHz")
    assert q_ghz.canonical_unit == "Hz"
    assert math.isclose(q_ghz.canonical_value, 2.4e9, rel_tol=1e-9)


def test_stem_unit_normalizer_temperature_affine_conversion():
    """Verify temperature conversion with affine offset (Celsius to Kelvin)."""
    normalizer = STEMUnitNormalizer()

    q_c = normalizer.normalize_quantity("25 °C")
    assert q_c.canonical_unit == "K"
    assert math.isclose(q_c.canonical_value, 298.15, rel_tol=1e-9)

    # Convert back to °C
    val_c = q_c.convert_to("°C")
    assert math.isclose(val_c, 25.0, rel_tol=1e-9)


def test_stem_unit_normalizer_pressure_and_energy():
    """Verify pressure (Pa) and energy (J) normalization and conversions."""
    normalizer = STEMUnitNormalizer()

    # kPa to Pa
    q_kpa = normalizer.normalize_quantity("101.325 kPa")
    assert q_kpa.canonical_unit == "Pa"
    assert math.isclose(q_kpa.canonical_value, 101325.0, rel_tol=1e-9)

    # Convert Pa to atm
    atm_val = q_kpa.convert_to("atm")
    assert math.isclose(atm_val, 1.0, rel_tol=1e-5)

    # eV to J
    q_ev = normalizer.normalize_quantity("3.5 eV")
    assert q_ev.canonical_unit == "J"
    assert math.isclose(q_ev.canonical_value, 3.5 * 1.602176634e-19, rel_tol=1e-9)


def test_unit_conversion_dimension_mismatch_error():
    """Verify rejection when converting between incompatible physical dimensions."""
    normalizer = STEMUnitNormalizer()
    q_len = normalizer.normalize_quantity("5.0 m")

    with pytest.raises(UnitConversionError, match="Dimension mismatch"):
        q_len.convert_to("kg")

    with pytest.raises(
        UnitConversionError, match="Target unit 'unknown_unit' is not in UNIT_REGISTRY"
    ):
        q_len.convert_to("unknown_unit")


def test_uncertainty_parsing_in_quantities():
    """Verify parsing and preservation of measurement uncertainty (e.g. 4.2 ± 0.1 µm)."""
    normalizer = STEMUnitNormalizer()
    q = normalizer.normalize_quantity("4.2 ± 0.1 µm")

    assert q.numeric_value == 4.2
    assert q.uncertainty == 0.1
    assert q.raw_unit == "µm"
    assert math.isclose(q.canonical_value, 4.2e-6, rel_tol=1e-9)


def test_extract_quantities_from_scientific_text():
    """Verify batch extraction of quantities with physical coordinates from text."""
    normalizer = STEMUnitNormalizer()
    text = (
        "The reaction proceeded for 45 min at 25 °C under a pressure of 100 kPa. "
        "A yield of 94.5 % was obtained with nanoparticles measuring 12.5 nm."
    )
    quantities = normalizer.extract_quantities(text, document_id="doc-exp-1")

    assert len(quantities) >= 5
    units = [q.raw_unit for q in quantities]
    assert "min" in units
    assert "°C" in units
    assert "kPa" in units
    assert "%" in units
    assert "nm" in units

    for q in quantities:
        assert q.coordinate is not None
        assert q.coordinate.char_start >= 0
        assert q.coordinate.char_end > q.coordinate.char_start
        assert q.coordinate.verbatim_snippet in text


def test_epistemic_classification_empirical():
    """Verify empirical classification for direct observations and measurements."""
    normalizer = STEMUnitNormalizer()
    sent = "We measured an optical density of 0.85 at 600 nm."
    assertion = normalizer.classify_epistemic_assertion(sent)

    assert assertion.epistemic_type == EpistemicAssertionType.EMPIRICAL
    assert assertion.confidence >= 0.80
    assert assertion.is_hedged is False


def test_epistemic_classification_correlational():
    """Verify correlational classification for association and covariance statements."""
    normalizer = STEMUnitNormalizer()
    sent = "Expression of gene BRCA1 was strongly correlated with patient survival."
    assertion = normalizer.classify_epistemic_assertion(sent)

    assert assertion.epistemic_type == EpistemicAssertionType.CORRELATIONAL
    assert assertion.confidence >= 0.85
    assert "correlated with" in " ".join(assertion.evidence_terms).lower()


def test_epistemic_classification_causal_interventional():
    """Verify causal classification only when directed causal verb and intervention are present."""
    normalizer = STEMUnitNormalizer()
    sent = "CRISPR knockout of kinase CDK4 caused a 50% reduction in cell proliferation."
    assertion = normalizer.classify_epistemic_assertion(sent)

    assert assertion.epistemic_type == EpistemicAssertionType.CAUSAL
    assert assertion.confidence >= 0.85


def test_epistemic_classification_speculative():
    """Verify speculative classification for theoretical hypotheses and hedged mechanisms."""
    normalizer = STEMUnitNormalizer()
    sent = "We hypothesize that compound X might potentially explain membrane permeabilization."
    assertion = normalizer.classify_epistemic_assertion(sent)

    assert assertion.epistemic_type == EpistemicAssertionType.SPECULATIVE
    assert assertion.is_hedged is True


def test_strict_anti_overreach_guardrail_prevents_correlation_to_causation():
    """Verify strict prohibition of correlation-to-causation promotion.

    CRITICAL ACCEPTANCE GATE: Correlational assertions must NEVER be promoted to CAUSAL.
    """
    normalizer = STEMUnitNormalizer()

    # Correlational sentence that uses causal-sounding phrasing in correlational context
    sent = (
        "Elevated blood biomarker levels are associated with disease onset, "
        "which leads to complications."
    )
    assertion = normalizer.classify_epistemic_assertion(sent)

    # Because "associated with" is present, it MUST be classified as CORRELATIONAL
    assert assertion.epistemic_type == EpistemicAssertionType.CORRELATIONAL

    # Verification function must raise EpistemicOverreachError if someone claims CAUSAL
    with pytest.raises(
        EpistemicOverreachError,
        match="Cannot promote correlational assertion .* to CAUSAL",
    ):
        normalizer.verify_no_epistemic_overreach(assertion, EpistemicAssertionType.CAUSAL)

    # Claiming CORRELATIONAL is accepted
    normalizer.verify_no_epistemic_overreach(assertion, EpistemicAssertionType.CORRELATIONAL)


def test_epistemic_overreach_invalid_input():
    """Verify contract violation error on invalid assertion type input."""
    normalizer = STEMUnitNormalizer()
    with pytest.raises(ModuleContractViolationError, match="Expected EpistemicAssertion"):
        normalizer.verify_no_epistemic_overreach("not-an-assertion", EpistemicAssertionType.CAUSAL)  # type: ignore


def test_serialization_and_roundtrip():
    """Verify JSON serialization for NormalizedQuantity and EpistemicAssertion."""
    normalizer = STEMUnitNormalizer()
    q = normalizer.normalize_quantity("15.5 mg")

    json_q = q.to_json()
    parsed_q = json.loads(json_q)
    assert parsed_q["raw_text"] == "15.5 mg"
    assert parsed_q["canonical_unit"] == "kg"
    assert parsed_q["numeric_value"] == 15.5

    assertion = normalizer.classify_epistemic_assertion(
        "Treatment with antibody A caused tumor regression."
    )
    json_a = assertion.to_json()
    parsed_a = json.loads(json_a)
    assert parsed_a["epistemic_type"] == "causal"


def test_parse_quantity_string_errors():
    """Verify error handling on invalid or malformed quantity strings."""
    normalizer = STEMUnitNormalizer()

    with pytest.raises(ModuleContractViolationError, match="must be a non-empty string"):
        normalizer.parse_quantity_string("")

    with pytest.raises(ModuleContractViolationError, match="must be a non-empty string"):
        normalizer.parse_quantity_string(None)  # type: ignore

    with pytest.raises(UnitConversionError, match="Could not parse valid quantity"):
        normalizer.parse_quantity_string("no-numbers-here")

    with pytest.raises(UnitConversionError, match="Unknown unit symbol"):
        normalizer.normalize_quantity("12.5 floobles")


def test_dimensional_vector_methods():
    """Verify DimensionalVector helper methods (dimensionless check, dict conversion)."""
    dim_scalar = DimensionalVector()
    assert dim_scalar.is_dimensionless() is True

    dim_force = DimensionalVector(length=1, mass=1, time=-2)
    assert dim_force.is_dimensionless() is False

    d_dict = dim_force.to_dict()
    assert d_dict["length"] == 1
    assert d_dict["mass"] == 1
    assert d_dict["time"] == -2

    restored = DimensionalVector.from_dict(d_dict)
    assert restored.is_compatible(dim_force)


def test_stem_unit_input_validation_and_dict_serialization():
    """Verify input validation and dict serialization across units and assertions."""
    normalizer = STEMUnitNormalizer()

    # extract_quantities validation
    with pytest.raises(ModuleContractViolationError, match="text must be a string"):
        normalizer.extract_quantities(12345)  # type: ignore

    # classify_epistemic_assertion validation
    with pytest.raises(ModuleContractViolationError, match="Sentence must be a non-empty string"):
        normalizer.classify_epistemic_assertion("")

    with pytest.raises(ModuleContractViolationError, match="Sentence must be a non-empty string"):
        normalizer.classify_epistemic_assertion(None)  # type: ignore

    # Default fallback classification on generic sentence without numbers
    generic_assertion = normalizer.classify_epistemic_assertion("The sky appears blue today.")
    assert generic_assertion.epistemic_type == EpistemicAssertionType.EMPIRICAL
    assert generic_assertion.confidence == 0.70

    # to_dict verification
    a_dict = generic_assertion.to_dict()
    assert a_dict["statement"] == "The sky appears blue today."
    assert a_dict["epistemic_type"] == "empirical"

    q = normalizer.normalize_quantity("25 °C")
    q_dict = q.to_dict()
    assert q_dict["raw_unit"] == "°C"
    assert q_dict["canonical_unit"] == "K"
    assert q_dict["offset"] == 273.15
