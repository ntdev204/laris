"""Synthetic corpus test fixtures for Layer 0 ingestion pipeline tests.

Provides deterministic, synthetic scientific documents with varied characteristics:
- Valid open-access licenses (CC-BY-4.0, CC0-1.0, MIT, Apache-2.0)
- Complex scientific formatting (LaTeX math, Greek letters, SI units, Unicode fullwidth)
- Exact duplicates and near-duplicate revisions
- Connected co-authorship graphs
- Single/isolated authors and anonymous documents
- Unauthorized or invalid documents for quarantine validation
"""

from typing import Dict, List

from laris.corpus.pipeline import RawDocumentInput
from laris.corpus.schemas import LicenseType


def get_standard_synthetic_corpus() -> List[RawDocumentInput]:
    """Returns a rich, deterministic set of synthetic raw documents for testing."""
    return [
        # doc-001: Standard paper with scientific text, SI units, math, co-authors Alice & Bob
        RawDocumentInput(
            corpus_id="synth-001",
            raw_text=(
                "Quantum electrodynamics in cavity optomechanics. "
                "The energy relation is given by $E = m c^2$ where mass $m$ operates at "
                "frequency 50 GHz with spatial cavity length 100 µm. "
                "Thermal dissipation occurs at 300 K with flux rate 2.5 mW/cm^2. "
                "Coupling parameter satisfies \u03b1 \u2264 \u03b2 under boundary condition \u03b3."
            ),
            declared_license=LicenseType.CC_BY_4_0,
            verification_source="https://arxiv.org/abs/2601.00001",
            verified_by="automated-curator",
            authorized=True,
            authors=["Alice Smith", "Bob Jones"],
            license_url="https://creativecommons.org/licenses/by/4.0/",
            metadata={"domain": "quantum_physics", "year": "2026"},
        ),
        # doc-001-exact-dup: Exact duplicate of synth-001 with trailing spaces and ligatures
        RawDocumentInput(
            corpus_id="synth-001-dup",
            raw_text=(
                "Quantum electrodynamics in cavity optomechanics. \n\n"
                "The energy relation is given by $E = m c^2$ where mass $m$ operates at "
                "frequency 50 GHz with spatial cavity length 100 µm. "
                "Thermal dissipation occurs at 300 K with flux rate 2.5 mW/cm^2. "
                "Coupling parameter satisfies \u03b1 \u2264 \u03b2 "
                "under boundary condition \u03b3.  "
            ),
            declared_license=LicenseType.CC_BY_4_0,
            verification_source="https://arxiv.org/abs/2601.00001v2",
            verified_by="automated-curator",
            authorized=True,
            authors=["Alice Smith", "Bob Jones"],
            license_url="https://creativecommons.org/licenses/by/4.0/",
            metadata={"domain": "quantum_physics", "year": "2026"},
        ),
        # doc-002: Near-duplicate revision of synth-001 (>0.85 Jaccard similarity)
        RawDocumentInput(
            corpus_id="synth-002-near",
            raw_text=(
                "Quantum electrodynamics in cavity optomechanics. "
                "The energy relation is given by $E = m c^2$ where mass $m$ operates at "
                "frequency 50 GHz with spatial cavity length 100 µm. "
                "Thermal dissipation occurs at 300 K with flux rate 2.5 mW/cm^2. "
                "Coupling parameter satisfies \u03b1 \u2264 \u03b2 "
                "under boundary condition \u03b3. "
                "Experimental verification confirms these findings."
            ),
            declared_license=LicenseType.CC_BY_4_0,
            verification_source="https://arxiv.org/abs/2601.00001v3",
            verified_by="automated-curator",
            authorized=True,
            authors=["Alice Smith", "Bob Jones"],
            license_url="https://creativecommons.org/licenses/by/4.0/",
            metadata={"domain": "quantum_physics", "version": "v3"},
        ),
        # doc-003: Connects Bob Jones with Charlie Brown (chain: Alice-Bob-Charlie)
        RawDocumentInput(
            corpus_id="synth-003",
            raw_text=(
                "High-throughput screening in biomedical imaging. "
                "We implement Bayesian optimization for microfluidic channels at 15 µL/min. "
                "The signal amplitude \u03b4 reaches maximum resolution at 12.5 MHz."
            ),
            declared_license=LicenseType.CC_BY_4_0,
            verification_source="https://arxiv.org/abs/2601.00003",
            verified_by="automated-curator",
            authorized=True,
            authors=["Bob Jones", "Charlie Brown"],
            license_url="https://creativecommons.org/licenses/by/4.0/",
            metadata={"domain": "biomedical", "year": "2026"},
        ),
        # doc-004: Connects Charlie Brown with David Wilson
        RawDocumentInput(
            corpus_id="synth-004",
            raw_text=(
                "Graph neural architectures for molecular property prediction. "
                "Message passing iteration \u03c4 converges in $O(V + E)$ steps. "
                "Empirical benchmarks demonstrate 4.2% lower RMSE across 15 target datasets."
            ),
            declared_license=LicenseType.ARXIV_NON_EXCLUSIVE,
            verification_source="https://arxiv.org/abs/2601.00004",
            verified_by="automated-curator",
            authorized=True,
            authors=["Charlie Brown", "David Wilson"],
            license_url="https://arxiv.org/licenses/nonexclusive-distrib/1.0/license.html",
            metadata={"domain": "graph_ml", "year": "2026"},
        ),
        # doc-005: Independent author Elena Rostova
        RawDocumentInput(
            corpus_id="synth-005",
            raw_text=(
                "Gravitational wave transient catalog analysis. "
                "Binary neutron star coalescence detected at redshift $z = 0.045$. "
                "Chirp mass measured as 1.18 solar masses with signal-to-noise ratio 32.4."
            ),
            declared_license=LicenseType.CC_BY_SA_4_0,
            verification_source="https://arxiv.org/abs/2601.00005",
            verified_by="automated-curator",
            authorized=True,
            authors=["Elena Rostova"],
            license_url="https://creativecommons.org/licenses/by-sa/4.0/",
            metadata={"domain": "astrophysics", "year": "2025"},
        ),
        # doc-006: Independent author Frank Zhang, MIT license
        RawDocumentInput(
            corpus_id="synth-006",
            raw_text=(
                "Topological insulators and Majorana fermions in semiconductor nanowires. "
                "Superconducting proximity induces zero-bias conductance peak at 0.05 K. "
                "Gate voltage modulation between -2.0 V and +1.5 V demonstrates phase transition."
            ),
            declared_license=LicenseType.MIT,
            verification_source="https://github.com/synth/topological-nanowires",
            verified_by="automated-curator",
            authorized=True,
            authors=["Frank Zhang"],
            license_url="https://opensource.org/licenses/MIT",
            metadata={"domain": "condensed_matter"},
        ),
        # doc-007: Independent author Grace Hopper, Apache-2.0 license
        RawDocumentInput(
            corpus_id="synth-007",
            raw_text=(
                "Compiler optimization routines for distributed scientific computing. "
                "Static single assignment form transformation reduces memory overhead by 18%. "
                "Execution latency benchmarked across 256 NUMA nodes."
            ),
            declared_license=LicenseType.APACHE_2_0,
            verification_source="https://github.com/synth/compiler-opt",
            verified_by="automated-curator",
            authorized=True,
            authors=["Grace Hopper"],
            license_url="https://www.apache.org/licenses/LICENSE-2.0",
            metadata={"domain": "compilers"},
        ),
        # doc-008: Anonymous / authorless document
        RawDocumentInput(
            corpus_id="synth-008-anon",
            raw_text=(
                "Community guidelines and dataset provenance standards for open science. "
                "Transparent reproducibility requires cryptographic verification of source corpora "
                "and strict validation against license contamination."
            ),
            declared_license=LicenseType.CC_BY_4_0,
            verification_source="https://openscience.org/manifesto",
            verified_by="automated-curator",
            authorized=True,
            authors=[],
            license_url="https://creativecommons.org/licenses/by/4.0/",
            metadata={"domain": "policy"},
        ),
        # doc-009: Unauthorized document (should be quarantined)
        RawDocumentInput(
            corpus_id="synth-009-unauthorized",
            raw_text="Confidential proprietary research notes. Do not distribute without NDA.",
            declared_license=LicenseType.PROPRIETARY_UNAUTHORIZED,
            verification_source="internal-leak",
            verified_by="security-audit",
            authorized=False,
            authors=["Corporate R&D"],
            license_url=None,
            metadata={"security_level": "classified"},
        ),
        # doc-010: Empty text document (should be quarantined)
        RawDocumentInput(
            corpus_id="synth-010-empty",
            raw_text="   \n\t  \r  ",
            declared_license=LicenseType.CC_BY_4_0,
            verification_source="empty-stream",
            verified_by="automated-curator",
            authorized=True,
            authors=["Ghost Writer"],
            license_url="https://creativecommons.org/licenses/by/4.0/",
            metadata={},
        ),
        # doc-011: Independent author Henry Ford
        RawDocumentInput(
            corpus_id="synth-011",
            raw_text=(
                "Catalytic cracking mechanisms in synthetic hydrocarbon polymers. "
                "Zeolite catalysts achieve 94% selectivity at reaction temperature 450 °C. "
                "Kinetic constants determined via gas chromatography."
            ),
            declared_license=LicenseType.CC_BY_4_0,
            verification_source="https://arxiv.org/abs/2601.00011",
            verified_by="automated-curator",
            authorized=True,
            authors=["Henry Ford"],
            license_url="https://creativecommons.org/licenses/by/4.0/",
            metadata={"domain": "chemistry"},
        ),
        # doc-012: Independent author Irene Adler
        RawDocumentInput(
            corpus_id="synth-012",
            raw_text=(
                "Coupled atmospheric-oceanic circulation models under thermal forcing. "
                "Meridional overturning circulation decelerates by 1.2 Sv per decade. "
                "Ensemble simulations resolve vorticity structures down to 10 km grid cells."
            ),
            declared_license=LicenseType.CC_BY_4_0,
            verification_source="https://arxiv.org/abs/2601.00012",
            verified_by="automated-curator",
            authorized=True,
            authors=["Irene Adler"],
            license_url="https://creativecommons.org/licenses/by/4.0/",
            metadata={"domain": "climatology"},
        ),
    ]


def get_synthetic_author_map(documents: List[RawDocumentInput]) -> Dict[str, List[str]]:
    """Extracts author mapping from a list of raw documents."""
    return {doc.corpus_id: list(doc.authors) for doc in documents}
