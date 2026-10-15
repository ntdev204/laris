"""Unit tests for Quantity Preservation and Epistemic Regression Safety.

Module ID: MOD-SCINLP-003 (Boundary D: Scientific Language Intelligence)
Subtask: M4-SCINLP-003-SUB-02 (Issue #90)
Parent Task: #26
Tests:
- Numerical magnitude preservation across extreme dynamic ranges (1e-24 to 1e12)
- Zero precision loss and roundtrip conversions for base, derived, and compound STEM units
- Compound unit normalization: velocity (m/s, km/h), acceleration (m/s^2), density (kg/m^3, g/cm^3),
  molar energy (J/mol, kJ/mol, kcal/mol), resistance (Ω, kΩ), force (N, kN), and power (W, kW, MW)
- Epistemic regression safety: strict prevention of correlation-to-causation promotion
- Benchmark report generation and serialization
"""

import json
import math

import pytest

from laris.core.errors import EpistemicOverreachError
from laris.layers.layer3_scinlp import (
    EpistemicAssertionType,
    PreservationBenchmarkResult,
    STEMUnitNormalizer,
)


def test_preservation_benchmark_suite_passes():
    """Verify that full quantity-preservation and epistemic regression suite passes all gates."""
    normalizer = STEMUnitNormalizer()
    report = normalizer.run_preservation_and_epistemic_regression()

    assert isinstance(report, PreservationBenchmarkResult)
    assert report.total_quantities_tested >= 19
    assert report.roundtrip_passed is True
    assert report.max_relative_error < 1e-12
    assert report.preservation_rate == 1.0
    assert report.epistemic_regression_passed is True
    assert report.overreach_attempts_blocked >= 2
    assert "Preservation benchmark:" in report.summary


def test_extreme_dynamic_range_magnitude_preservation():
    """Verify zero precision loss across 36 orders of magnitude (1e-24 to 1e12)."""
    normalizer = STEMUnitNormalizer()

    # Subatomic mass: 1 Da ~ 1.66053906660e-27 kg
    q_da = normalizer.normalize_quantity("1.0 Da")
    assert math.isclose(q_da.canonical_value, 1.66053906660e-27, rel_tol=1e-12)
    assert math.isclose(q_da.convert_to("Da"), 1.0, rel_tol=1e-12)

    # Quantum energy: 1.0 eV ~ 1.602176634e-19 J
    q_ev = normalizer.normalize_quantity("1.0 eV")
    assert math.isclose(q_ev.canonical_value, 1.602176634e-19, rel_tol=1e-12)
    assert math.isclose(q_ev.convert_to("eV"), 1.0, rel_tol=1e-12)

    # Terahertz frequency: 5.5 THz = 5.5e12 Hz
    q_thz = normalizer.normalize_quantity("5.5 THz")
    assert math.isclose(q_thz.canonical_value, 5.5e12, rel_tol=1e-12)
    assert math.isclose(q_thz.convert_to("THz"), 5.5, rel_tol=1e-12)

    # Gigapascal pressure: 2.5 GPa = 2.5e9 Pa
    q_gpa = normalizer.normalize_quantity("2.5 GPa")
    assert math.isclose(q_gpa.canonical_value, 2.5e9, rel_tol=1e-12)
    assert math.isclose(q_gpa.convert_to("GPa"), 2.5, rel_tol=1e-12)


def test_compound_units_velocity_and_acceleration():
    """Verify compound velocity (m/s, km/h) and acceleration (m/s^2) normalization."""
    normalizer = STEMUnitNormalizer()

    # 36 km/h == 10 m/s
    q_vel = normalizer.normalize_quantity("36 km/h")
    assert q_vel.canonical_unit == "m/s"
    assert math.isclose(q_vel.canonical_value, 10.0, rel_tol=1e-9)
    assert math.isclose(q_vel.convert_to("km/h"), 36.0, rel_tol=1e-9)

    # Acceleration
    q_acc = normalizer.normalize_quantity("9.81 m/s^2")
    assert q_acc.canonical_unit == "m/s^2"
    assert math.isclose(q_acc.canonical_value, 9.81, rel_tol=1e-9)
    assert math.isclose(q_acc.convert_to("m/s^2"), 9.81, rel_tol=1e-9)


def test_compound_units_density_and_molar_energy():
    """Verify compound density (g/cm^3 to kg/m^3) and molar energy (kcal/mol to J/mol)."""
    normalizer = STEMUnitNormalizer()

    # Water density: 1 g/cm^3 = 1000 kg/m^3
    q_dens = normalizer.normalize_quantity("1.0 g/cm^3")
    assert q_dens.canonical_unit == "kg/m^3"
    assert math.isclose(q_dens.canonical_value, 1000.0, rel_tol=1e-9)
    assert math.isclose(q_dens.convert_to("g/cm^3"), 1.0, rel_tol=1e-9)
    assert math.isclose(q_dens.convert_to("mg/mL"), 1000.0, rel_tol=1e-9)

    # Molar binding energy: 1 kcal/mol = 4184 J/mol
    q_energy = normalizer.normalize_quantity("10.0 kcal/mol")
    assert q_energy.canonical_unit == "J/mol"
    assert math.isclose(q_energy.canonical_value, 41840.0, rel_tol=1e-9)
    assert math.isclose(q_energy.convert_to("kcal/mol"), 10.0, rel_tol=1e-9)
    assert math.isclose(q_energy.convert_to("kJ/mol"), 41.84, rel_tol=1e-9)


def test_compound_units_resistance_force_power():
    """Verify electrical resistance (Ω), force (N), and power (W) normalization."""
    normalizer = STEMUnitNormalizer()

    # Resistance: 4.7 kΩ = 4700 Ω
    q_res = normalizer.normalize_quantity("4.7 kΩ")
    assert q_res.canonical_unit == "Ω"
    assert math.isclose(q_res.canonical_value, 4700.0, rel_tol=1e-9)
    assert math.isclose(q_res.convert_to("kΩ"), 4.7, rel_tol=1e-9)

    # Force: 2.5 kN = 2500 N
    q_force = normalizer.normalize_quantity("2.5 kN")
    assert q_force.canonical_unit == "N"
    assert math.isclose(q_force.canonical_value, 2500.0, rel_tol=1e-9)
    assert math.isclose(q_force.convert_to("kN"), 2.5, rel_tol=1e-9)

    # Power: 10 MW = 1e7 W
    q_pow = normalizer.normalize_quantity("10 MW")
    assert q_pow.canonical_unit == "W"
    assert math.isclose(q_pow.canonical_value, 1e7, rel_tol=1e-9)
    assert math.isclose(q_pow.convert_to("MW"), 10.0, rel_tol=1e-9)
    assert math.isclose(q_pow.convert_to("kW"), 10000.0, rel_tol=1e-9)


def test_epistemic_regression_seductive_correlation_with_causal_verbs():
    """Verify that correlational assertions containing causal verbs remain CORRELATIONAL."""
    normalizer = STEMUnitNormalizer()

    # Sentence uses "leads to" within a correlational observation
    text1 = (
        "High dietary sodium intake was correlated with arterial stiffness, "
        "which leads to systolic hypertension in older adults."
    )
    a1 = normalizer.classify_epistemic_assertion(text1)
    assert a1.epistemic_type == EpistemicAssertionType.CORRELATIONAL

    # Must raise EpistemicOverreachError if anyone attempts to promote to CAUSAL
    with pytest.raises(EpistemicOverreachError, match="Cannot promote correlational assertion"):
        normalizer.verify_no_epistemic_overreach(a1, EpistemicAssertionType.CAUSAL)

    # Sentence uses "statistically linked to" alongside "triggers"
    text2 = (
        "Polymorphism rs429358 is statistically linked to amyloid plaque load, "
        "which triggers neuroinflammation."
    )
    a2 = normalizer.classify_epistemic_assertion(text2)
    assert a2.epistemic_type == EpistemicAssertionType.CORRELATIONAL

    with pytest.raises(EpistemicOverreachError, match="Cannot promote correlational assertion"):
        normalizer.verify_no_epistemic_overreach(a2, EpistemicAssertionType.CAUSAL)


def test_epistemic_regression_speculative_with_causal_verbs():
    """Verify that speculative statements containing causal verbs remain SPECULATIVE."""
    normalizer = STEMUnitNormalizer()

    # Speculative hypothesis using "causes"
    text = "We hypothesize that loss of epigenetic silencing might cause ectopic gene activation."
    assertion = normalizer.classify_epistemic_assertion(text)
    assert assertion.epistemic_type == EpistemicAssertionType.SPECULATIVE
    assert assertion.is_hedged is True


def test_preservation_benchmark_report_serialization():
    """Verify JSON and dict serialization for PreservationBenchmarkResult."""
    normalizer = STEMUnitNormalizer()
    report = normalizer.run_preservation_and_epistemic_regression()

    d = report.to_dict()
    assert d["roundtrip_passed"] is True
    assert d["preservation_rate"] == 1.0
    assert d["epistemic_regression_passed"] is True

    json_str = report.to_json()
    parsed = json.loads(json_str)
    assert parsed["max_relative_error"] < 1e-12
    assert parsed["epistemic_assertions_tested"] >= 7
