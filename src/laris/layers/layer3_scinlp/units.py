"""STEM Unit and Epistemic Status Normalizer.

Module ID: MOD-SCINLP-003 (Boundary D: Scientific Language Intelligence)
Governed by: docs/specifications/MODULE_CONTRACTS.md, ADR-002, ADR-008.
Normalizes SI and STEM units to canonical base representations with zero precision loss,
performs dimensional analysis, and classifies scientific assertions into empirical,
correlational, causal, and speculative categories with strict epistemic guardrails.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from laris.core.errors import (
    EpistemicOverreachError,
    ModuleContractViolationError,
    UnitConversionError,
)
from laris.core.schemas import EvidenceCoordinate


class BaseDimension(str, Enum):
    """Fundamental SI dimensions for dimensional analysis."""

    LENGTH = "length"
    MASS = "mass"
    TIME = "time"
    ELECTRIC_CURRENT = "electric_current"
    TEMPERATURE = "temperature"
    AMOUNT_OF_SUBSTANCE = "amount_of_substance"
    LUMINOUS_INTENSITY = "luminous_intensity"
    DIMENSIONLESS = "dimensionless"


class EpistemicAssertionType(str, Enum):
    """Epistemic classification of scientific claims and quantitative statements."""

    EMPIRICAL = "empirical"
    CORRELATIONAL = "correlational"
    CAUSAL = "causal"
    SPECULATIVE = "speculative"


@dataclass(frozen=True)
class DimensionalVector:
    """Integer vector representing powers of fundamental SI dimensions."""

    length: int = 0
    mass: int = 0
    time: int = 0
    electric_current: int = 0
    temperature: int = 0
    amount_of_substance: int = 0
    luminous_intensity: int = 0

    def is_compatible(self, other: DimensionalVector) -> bool:
        """Check if two dimensional vectors represent the same physical dimension."""
        return (
            self.length == other.length
            and self.mass == other.mass
            and self.time == other.time
            and self.electric_current == other.electric_current
            and self.temperature == other.temperature
            and self.amount_of_substance == other.amount_of_substance
            and self.luminous_intensity == other.luminous_intensity
        )

    def is_dimensionless(self) -> bool:
        """Check if all dimensional exponents are zero."""
        return (
            self.length == 0
            and self.mass == 0
            and self.time == 0
            and self.electric_current == 0
            and self.temperature == 0
            and self.amount_of_substance == 0
            and self.luminous_intensity == 0
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "length": self.length,
            "mass": self.mass,
            "time": self.time,
            "electric_current": self.electric_current,
            "temperature": self.temperature,
            "amount_of_substance": self.amount_of_substance,
            "luminous_intensity": self.luminous_intensity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, int]) -> DimensionalVector:
        return cls(
            length=data.get("length", 0),
            mass=data.get("mass", 0),
            time=data.get("time", 0),
            electric_current=data.get("electric_current", 0),
            temperature=data.get("temperature", 0),
            amount_of_substance=data.get("amount_of_substance", 0),
            luminous_intensity=data.get("luminous_intensity", 0),
        )


# Canonical Dimensional Vectors
DIM_DIMENSIONLESS = DimensionalVector()
DIM_LENGTH = DimensionalVector(length=1)
DIM_MASS = DimensionalVector(mass=1)
DIM_TIME = DimensionalVector(time=1)
DIM_CURRENT = DimensionalVector(electric_current=1)
DIM_TEMPERATURE = DimensionalVector(temperature=1)
DIM_SUBSTANCE = DimensionalVector(amount_of_substance=1)
DIM_LUMINOUS = DimensionalVector(luminous_intensity=1)

# Derived dimensions
DIM_AREA = DimensionalVector(length=2)
DIM_VOLUME = DimensionalVector(length=3)
DIM_VELOCITY = DimensionalVector(length=1, time=-1)
DIM_FORCE = DimensionalVector(length=1, mass=1, time=-2)  # N = kg*m/s^2
DIM_PRESSURE = DimensionalVector(length=-1, mass=1, time=-2)  # Pa = kg/(m*s^2)
DIM_ENERGY = DimensionalVector(length=2, mass=1, time=-2)  # J = kg*m^2/s^2
DIM_POWER = DimensionalVector(length=2, mass=1, time=-3)  # W = J/s
DIM_VOLTAGE = DimensionalVector(length=2, mass=1, time=-3, electric_current=-1)  # V
DIM_FREQUENCY = DimensionalVector(time=-1)  # Hz = 1/s
DIM_CONCENTRATION = DimensionalVector(length=-3, amount_of_substance=1)  # mol/m^3


@dataclass(frozen=True)
class UnitSpec:
    """Specification of a physical unit, its canonical SI base unit, dimension, and scaling."""

    symbol: str
    canonical_unit: str
    dimension: DimensionalVector
    scale_factor: float
    offset: float = 0.0


# Comprehensive SI and STEM Unit Registry
UNIT_REGISTRY: dict[str, UnitSpec] = {
    # Length (base: m)
    "m": UnitSpec("m", "m", DIM_LENGTH, 1.0),
    "meter": UnitSpec("meter", "m", DIM_LENGTH, 1.0),
    "meters": UnitSpec("meters", "m", DIM_LENGTH, 1.0),
    "km": UnitSpec("km", "m", DIM_LENGTH, 1000.0),
    "cm": UnitSpec("cm", "m", DIM_LENGTH, 1e-2),
    "mm": UnitSpec("mm", "m", DIM_LENGTH, 1e-3),
    "µm": UnitSpec("µm", "m", DIM_LENGTH, 1e-6),
    "um": UnitSpec("um", "m", DIM_LENGTH, 1e-6),
    "micron": UnitSpec("micron", "m", DIM_LENGTH, 1e-6),
    "microns": UnitSpec("microns", "m", DIM_LENGTH, 1e-6),
    "nm": UnitSpec("nm", "m", DIM_LENGTH, 1e-9),
    "pm": UnitSpec("pm", "m", DIM_LENGTH, 1e-12),
    "Å": UnitSpec("Å", "m", DIM_LENGTH, 1e-10),
    "angstrom": UnitSpec("angstrom", "m", DIM_LENGTH, 1e-10),
    # Mass (base: kg)
    "kg": UnitSpec("kg", "kg", DIM_MASS, 1.0),
    "kilogram": UnitSpec("kilogram", "kg", DIM_MASS, 1.0),
    "g": UnitSpec("g", "kg", DIM_MASS, 1e-3),
    "gram": UnitSpec("gram", "kg", DIM_MASS, 1e-3),
    "mg": UnitSpec("mg", "kg", DIM_MASS, 1e-6),
    "milligram": UnitSpec("milligram", "kg", DIM_MASS, 1e-6),
    "µg": UnitSpec("µg", "kg", DIM_MASS, 1e-9),
    "ug": UnitSpec("ug", "kg", DIM_MASS, 1e-9),
    "ng": UnitSpec("ng", "kg", DIM_MASS, 1e-12),
    "Da": UnitSpec("Da", "kg", DIM_MASS, 1.66053906660e-27),
    "dalton": UnitSpec("dalton", "kg", DIM_MASS, 1.66053906660e-27),
    "kDa": UnitSpec("kDa", "kg", DIM_MASS, 1.66053906660e-24),
    # Time (base: s)
    "s": UnitSpec("s", "s", DIM_TIME, 1.0),
    "sec": UnitSpec("sec", "s", DIM_TIME, 1.0),
    "second": UnitSpec("second", "s", DIM_TIME, 1.0),
    "seconds": UnitSpec("seconds", "s", DIM_TIME, 1.0),
    "ms": UnitSpec("ms", "s", DIM_TIME, 1e-3),
    "µs": UnitSpec("µs", "s", DIM_TIME, 1e-6),
    "us": UnitSpec("us", "s", DIM_TIME, 1e-6),
    "ns": UnitSpec("ns", "s", DIM_TIME, 1e-9),
    "ps": UnitSpec("ps", "s", DIM_TIME, 1e-12),
    "min": UnitSpec("min", "s", DIM_TIME, 60.0),
    "h": UnitSpec("h", "s", DIM_TIME, 3600.0),
    "hr": UnitSpec("hr", "s", DIM_TIME, 3600.0),
    "d": UnitSpec("d", "s", DIM_TIME, 86400.0),
    "day": UnitSpec("day", "s", DIM_TIME, 86400.0),
    # Temperature (base: K)
    "K": UnitSpec("K", "K", DIM_TEMPERATURE, 1.0),
    "kelvin": UnitSpec("kelvin", "K", DIM_TEMPERATURE, 1.0),
    "°C": UnitSpec("°C", "K", DIM_TEMPERATURE, 1.0, offset=273.15),
    "degC": UnitSpec("degC", "K", DIM_TEMPERATURE, 1.0, offset=273.15),
    "C": UnitSpec("C", "K", DIM_TEMPERATURE, 1.0, offset=273.15),
    # Amount of substance (base: mol)
    "mol": UnitSpec("mol", "mol", DIM_SUBSTANCE, 1.0),
    "mole": UnitSpec("mole", "mol", DIM_SUBSTANCE, 1.0),
    "mmol": UnitSpec("mmol", "mol", DIM_SUBSTANCE, 1e-3),
    "µmol": UnitSpec("µmol", "mol", DIM_SUBSTANCE, 1e-6),
    "umol": UnitSpec("umol", "mol", DIM_SUBSTANCE, 1e-6),
    "nmol": UnitSpec("nmol", "mol", DIM_SUBSTANCE, 1e-9),
    "pmol": UnitSpec("pmol", "mol", DIM_SUBSTANCE, 1e-12),
    # Concentration (base: mol/m^3; 1 M = 1 mol/L = 1000 mol/m^3)
    "M": UnitSpec("M", "mol/m^3", DIM_CONCENTRATION, 1000.0),
    "molar": UnitSpec("molar", "mol/m^3", DIM_CONCENTRATION, 1000.0),
    "mM": UnitSpec("mM", "mol/m^3", DIM_CONCENTRATION, 1.0),
    "µM": UnitSpec("µM", "mol/m^3", DIM_CONCENTRATION, 1e-3),
    "uM": UnitSpec("uM", "mol/m^3", DIM_CONCENTRATION, 1e-3),
    "nM": UnitSpec("nM", "mol/m^3", DIM_CONCENTRATION, 1e-6),
    "pM": UnitSpec("pM", "mol/m^3", DIM_CONCENTRATION, 1e-9),
    # Pressure (base: Pa)
    "Pa": UnitSpec("Pa", "Pa", DIM_PRESSURE, 1.0),
    "pascal": UnitSpec("pascal", "Pa", DIM_PRESSURE, 1.0),
    "kPa": UnitSpec("kPa", "Pa", DIM_PRESSURE, 1000.0),
    "MPa": UnitSpec("MPa", "Pa", DIM_PRESSURE, 1e6),
    "GPa": UnitSpec("GPa", "Pa", DIM_PRESSURE, 1e9),
    "bar": UnitSpec("bar", "Pa", DIM_PRESSURE, 1e5),
    "mbar": UnitSpec("mbar", "Pa", DIM_PRESSURE, 100.0),
    "atm": UnitSpec("atm", "Pa", DIM_PRESSURE, 101325.0),
    "torr": UnitSpec("torr", "Pa", DIM_PRESSURE, 133.322368),
    "mmHg": UnitSpec("mmHg", "Pa", DIM_PRESSURE, 133.322368),
    # Energy (base: J)
    "J": UnitSpec("J", "J", DIM_ENERGY, 1.0),
    "joule": UnitSpec("joule", "J", DIM_ENERGY, 1.0),
    "kJ": UnitSpec("kJ", "J", DIM_ENERGY, 1000.0),
    "MJ": UnitSpec("MJ", "J", DIM_ENERGY, 1e6),
    "eV": UnitSpec("eV", "J", DIM_ENERGY, 1.602176634e-19),
    "keV": UnitSpec("keV", "J", DIM_ENERGY, 1.602176634e-16),
    "MeV": UnitSpec("MeV", "J", DIM_ENERGY, 1.602176634e-13),
    "cal": UnitSpec("cal", "J", DIM_ENERGY, 4.184),
    "kcal": UnitSpec("kcal", "J", DIM_ENERGY, 4184.0),
    # Frequency (base: Hz = 1/s)
    "Hz": UnitSpec("Hz", "Hz", DIM_FREQUENCY, 1.0),
    "kHz": UnitSpec("kHz", "Hz", DIM_FREQUENCY, 1000.0),
    "MHz": UnitSpec("MHz", "Hz", DIM_FREQUENCY, 1e6),
    "GHz": UnitSpec("GHz", "Hz", DIM_FREQUENCY, 1e9),
    "THz": UnitSpec("THz", "Hz", DIM_FREQUENCY, 1e12),
    # Electric Current & Potential
    "A": UnitSpec("A", "A", DIM_CURRENT, 1.0),
    "mA": UnitSpec("mA", "A", DIM_CURRENT, 1e-3),
    "µA": UnitSpec("µA", "A", DIM_CURRENT, 1e-6),
    "uA": UnitSpec("uA", "A", DIM_CURRENT, 1e-6),
    "nA": UnitSpec("nA", "A", DIM_CURRENT, 1e-9),
    "pA": UnitSpec("pA", "A", DIM_CURRENT, 1e-12),
    "V": UnitSpec("V", "V", DIM_VOLTAGE, 1.0),
    "volt": UnitSpec("volt", "V", DIM_VOLTAGE, 1.0),
    "mV": UnitSpec("mV", "V", DIM_VOLTAGE, 1e-3),
    "kV": UnitSpec("kV", "V", DIM_VOLTAGE, 1000.0),
    # Dimensionless
    "%": UnitSpec("%", "dimensionless", DIM_DIMENSIONLESS, 0.01),
    "percent": UnitSpec("percent", "dimensionless", DIM_DIMENSIONLESS, 0.01),
    "ppm": UnitSpec("ppm", "dimensionless", DIM_DIMENSIONLESS, 1e-6),
    "ppb": UnitSpec("ppb", "dimensionless", DIM_DIMENSIONLESS, 1e-9),
}


@dataclass(frozen=True)
class NormalizedQuantity:
    """A scientific quantity normalized to its canonical SI base unit."""

    raw_text: str
    numeric_value: float
    raw_unit: str
    canonical_value: float
    canonical_unit: str
    dimension: DimensionalVector
    scale_factor: float
    offset: float = 0.0
    uncertainty: float | None = None
    coordinate: EvidenceCoordinate | None = None

    def convert_to(self, target_unit: str) -> float:
        """Convert the quantity to a target compatible unit."""
        if target_unit not in UNIT_REGISTRY:
            raise UnitConversionError(f"Target unit '{target_unit}' is not in UNIT_REGISTRY.")
        target_spec = UNIT_REGISTRY[target_unit]
        if not self.dimension.is_compatible(target_spec.dimension):
            raise UnitConversionError(
                f"Dimension mismatch: cannot convert from {self.raw_unit} "
                f"to {target_unit} (incompatible dimensions)."
            )

        # Convert canonical SI value back to target unit
        if target_spec.offset != 0.0:
            return (self.canonical_value - target_spec.offset) / target_spec.scale_factor
        return self.canonical_value / target_spec.scale_factor

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "numeric_value": self.numeric_value,
            "raw_unit": self.raw_unit,
            "canonical_value": self.canonical_value,
            "canonical_unit": self.canonical_unit,
            "dimension": self.dimension.to_dict(),
            "scale_factor": self.scale_factor,
            "offset": self.offset,
            "uncertainty": self.uncertainty,
            "coordinate": asdict(self.coordinate) if self.coordinate else None,
        }

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class EpistemicAssertion:
    """A scientific claim or assertion classified by epistemic status with evidence."""

    statement: str
    epistemic_type: EpistemicAssertionType
    confidence: float
    evidence_terms: list[str] = field(default_factory=list)
    is_hedged: bool = False
    coordinate: EvidenceCoordinate | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement": self.statement,
            "epistemic_type": self.epistemic_type.value,
            "confidence": self.confidence,
            "evidence_terms": self.evidence_terms,
            "is_hedged": self.is_hedged,
            "coordinate": asdict(self.coordinate) if self.coordinate else None,
        }

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# --- Epistemic Regex Patterns ---

CORRELATIONAL_PATTERNS = re.compile(
    r"\b(correlated with|correlates with|correlation between|associated with|"
    r"association between|statistically linked to|covaries with|co-occurred with|"
    r"co-expression of|linear relationship with|concordant with|coupled with|"
    r"in proportion to|coincided with|parallel trend)\b",
    re.IGNORECASE,
)

INTERVENTION_PATTERNS = re.compile(
    r"\b(knockdown|knockout|crispr|inhibitor|administered|administration of|"
    r"treatment with|treated with|injection of|depletion of|overexpression of|"
    r"mutation of|ablation of|perturbation of|randomized trial|intervention)\b",
    re.IGNORECASE,
)

DIRECTED_CAUSAL_PATTERNS = re.compile(
    r"\b(caused|induces|induced|drives|driven by|results in|resulted in|"
    r"leads to|led to|triggers|triggered|promotes|represses|repressed|"
    r"directly inhibits|directly activates|attenuated|rescued the phenotype)\b",
    re.IGNORECASE,
)

SPECULATIVE_PATTERNS = re.compile(
    r"\b(we hypothesize that|we postulate that|might indicate|could potentially explain|"
    r"suggests that|plausibly reflects|it is tempting to speculate|"
    r"may suggest|hints at|warrants further investigation|tentative hypothesis)\b",
    re.IGNORECASE,
)

EMPIRICAL_MEASUREMENT_PATTERNS = re.compile(
    r"\b(we measured|was observed to be|yielded a value of|measured at|"
    r"recorded an average of|quantified at|exhibited an optical density of|"
    r"titrated to|determined by mass spectrometry to be|assayed at)\b",
    re.IGNORECASE,
)

# Quantity extraction regex matching numbers, scientific notation, uncertainties, and units
QUANTITY_REGEX = re.compile(
    r"(?P<val>[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
    r"(?:\s*±\s*(?P<unc>\d+(?:\.\d+)?))?"
    r"\s*(?P<unit>(?:[°µÅ]|[a-zA-Z%])+(?:/(?:[°µÅ]|[a-zA-Z%])+)?(?:\^[0-9]+)?)",
    re.UNICODE,
)


class STEMUnitNormalizer:
    """Normalizes STEM units, performs dimensional verification, and assigns epistemic labels."""

    def __init__(self) -> None:
        pass

    def parse_quantity_string(self, text: str) -> tuple[float, str, float | None]:
        """Extract numeric value, unit symbol, and uncertainty from a concise quantity string."""
        if not isinstance(text, str) or not text.strip():
            raise ModuleContractViolationError("Quantity text must be a non-empty string.")

        match = QUANTITY_REGEX.search(text.strip())
        if not match:
            raise UnitConversionError(f"Could not parse valid quantity and unit from: '{text}'")

        val_str = match.group("val")
        unit_str = match.group("unit")
        unc_str = match.group("unc")

        try:
            val = float(val_str)
        except ValueError as err:
            raise ModuleContractViolationError(
                f"Invalid numeric quantity: '{val_str}'"
            ) from err

        unc = float(unc_str) if unc_str else None
        return val, unit_str, unc

    def normalize_quantity(
        self,
        raw_text: str,
        coordinate: EvidenceCoordinate | None = None,
    ) -> NormalizedQuantity:
        """Parse raw quantity string and normalize to canonical SI representation."""
        val, unit_str, unc = self.parse_quantity_string(raw_text)

        if unit_str not in UNIT_REGISTRY:
            raise UnitConversionError(
                f"Unknown unit symbol '{unit_str}'. Not recognized in UNIT_REGISTRY."
            )

        spec = UNIT_REGISTRY[unit_str]
        canonical_val = (val * spec.scale_factor) + spec.offset

        return NormalizedQuantity(
            raw_text=raw_text.strip(),
            numeric_value=val,
            raw_unit=unit_str,
            canonical_value=canonical_val,
            canonical_unit=spec.canonical_unit,
            dimension=spec.dimension,
            scale_factor=spec.scale_factor,
            offset=spec.offset,
            uncertainty=unc,
            coordinate=coordinate,
        )

    def extract_quantities(
        self,
        text: str,
        document_id: str = "doc-stem",
    ) -> list[NormalizedQuantity]:
        """Extract all known scientific quantities from text and anchor with coordinates."""
        if not isinstance(text, str):
            raise ModuleContractViolationError("text must be a string.")

        quantities: list[NormalizedQuantity] = []
        for match in QUANTITY_REGEX.finditer(text):
            start = match.start()
            end = match.end()
            raw_snippet = match.group(0)
            val_str = match.group("val")
            unit_str = match.group("unit")
            unc_str = match.group("unc")

            if unit_str not in UNIT_REGISTRY:
                continue

            try:
                val = float(val_str)
            except ValueError:
                continue

            unc = float(unc_str) if unc_str else None
            spec = UNIT_REGISTRY[unit_str]
            canonical_val = (val * spec.scale_factor) + spec.offset

            coord = EvidenceCoordinate(
                coordinate_id=f"{document_id}:q:{start}-{end}",
                document_id=document_id,
                document_sha256="",
                page_number=1,
                section_identifier="body",
                paragraph_index=0,
                sentence_index=0,
                char_start=start,
                char_end=end,
                verbatim_snippet=raw_snippet,
                extraction_confidence=0.95,
            )

            quantities.append(
                NormalizedQuantity(
                    raw_text=raw_snippet,
                    numeric_value=val,
                    raw_unit=unit_str,
                    canonical_value=canonical_val,
                    canonical_unit=spec.canonical_unit,
                    dimension=spec.dimension,
                    scale_factor=spec.scale_factor,
                    offset=spec.offset,
                    uncertainty=unc,
                    coordinate=coord,
                )
            )

        return quantities

    def classify_epistemic_assertion(
        self,
        sentence: str,
        coordinate: EvidenceCoordinate | None = None,
    ) -> EpistemicAssertion:
        """Classify assertion epistemic status with strict anti-overreach guardrails.

        CRITICAL GUARDRAIL: A correlational assertion is NEVER classified as CAUSAL.
        """
        if not isinstance(sentence, str) or not sentence.strip():
            raise ModuleContractViolationError("Sentence must be a non-empty string.")

        sent = sentence.strip()
        matched_corr = CORRELATIONAL_PATTERNS.findall(sent)
        matched_spec = SPECULATIVE_PATTERNS.findall(sent)
        matched_interv = INTERVENTION_PATTERNS.findall(sent)
        matched_causal = DIRECTED_CAUSAL_PATTERNS.findall(sent)
        matched_emp = EMPIRICAL_MEASUREMENT_PATTERNS.findall(sent)

        # 1. Speculative takes precedence if explicit hypothesis or speculative hedge is present
        if matched_spec:
            return EpistemicAssertion(
                statement=sent,
                epistemic_type=EpistemicAssertionType.SPECULATIVE,
                confidence=0.90,
                evidence_terms=list(set(matched_spec)),
                is_hedged=True,
                coordinate=coordinate,
            )

        # 2. Correlational Guardrail: If correlation terms are present, NEVER classify as CAUSAL
        if matched_corr:
            return EpistemicAssertion(
                statement=sent,
                epistemic_type=EpistemicAssertionType.CORRELATIONAL,
                confidence=0.92,
                evidence_terms=list(set(matched_corr)),
                is_hedged=False,
                coordinate=coordinate,
            )

        # 3. Directed Causal: Requires causal verbs AND interventional context
        if matched_causal and matched_interv:
            return EpistemicAssertion(
                statement=sent,
                epistemic_type=EpistemicAssertionType.CAUSAL,
                confidence=0.88,
                evidence_terms=list(set(matched_causal + matched_interv)),
                is_hedged=False,
                coordinate=coordinate,
            )

        # 4. Empirical: Direct observation or measured values
        if matched_emp or QUANTITY_REGEX.search(sent):
            evidence = list(set(matched_emp)) if matched_emp else ["quantitative_measurement"]
            return EpistemicAssertion(
                statement=sent,
                epistemic_type=EpistemicAssertionType.EMPIRICAL,
                confidence=0.85,
                evidence_terms=evidence,
                is_hedged=False,
                coordinate=coordinate,
            )

        # Default fallback: Empirical observation
        return EpistemicAssertion(
            statement=sent,
            epistemic_type=EpistemicAssertionType.EMPIRICAL,
            confidence=0.70,
            evidence_terms=[],
            is_hedged=False,
            coordinate=coordinate,
        )

    def verify_no_epistemic_overreach(
        self,
        assertion: EpistemicAssertion,
        claimed_type: EpistemicAssertionType,
    ) -> None:
        """Verify that an assertion is not erroneously promoted from correlational to causal."""
        if not isinstance(assertion, EpistemicAssertion):
            raise ModuleContractViolationError(
                f"Expected EpistemicAssertion, got {type(assertion).__name__}"
            )

        if (
            assertion.epistemic_type == EpistemicAssertionType.CORRELATIONAL
            and claimed_type == EpistemicAssertionType.CAUSAL
        ):
            raise EpistemicOverreachError(
                f"Epistemic Overreach Violation: Cannot promote correlational assertion "
                f"'{assertion.statement}' to CAUSAL without experimental intervention."
            )
