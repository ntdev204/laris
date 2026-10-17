"""Versioned STEM benchmark synthetic text fixtures for tokenizer evaluation.

Provides curated domain sentences across major scientific fields:
- Physics (quantum electrodynamics, cavity optomechanics, superconductors)
- Chemistry (catalytic cracking, polymer synthesis, stoichiometric reactions)
- Biology (microfluidic sequencing, CRISPR endonuclease, transmembrane receptors)
- Computer Science (graph neural networks, static single assignment, message passing)
- Mathematics (differential manifolds, topological invariants, spectral radius)
"""

from dataclasses import dataclass
from typing import List

STEM_BENCHMARK_VERSION = "1.0.0"


@dataclass(frozen=True)
class StemBenchmarkSample:
    """A versioned benchmark sentence from a specific STEM domain."""

    sample_id: str
    domain: str
    text: str
    keywords: List[str]


STEM_BENCHMARK_FIXTURES: List[StemBenchmarkSample] = [
    StemBenchmarkSample(
        sample_id="stem-phys-001",
        domain="physics",
        text=(
            "Quantum electrodynamics in cavity optomechanics demonstrates photon-phonon "
            "coupling under cryogenic conditions at 15 mK with resonance frequency 50 GHz."
        ),
        keywords=["electrodynamics", "optomechanics", "photon-phonon", "cryogenic"],
    ),
    StemBenchmarkSample(
        sample_id="stem-phys-002",
        domain="physics",
        text=(
            "Majorana zero-bias conductance anomalies in superconductor-semiconductor "
            "heterostructures indicate non-Abelian topological phase transitions."
        ),
        keywords=["conductance", "heterostructures", "non-Abelian", "superconductor"],
    ),
    StemBenchmarkSample(
        sample_id="stem-chem-001",
        domain="chemistry",
        text=(
            "Zeolite-catalyzed cracking of polyolefin oligomers yields high-octane "
            "branched hydrocarbons with 92% enantiomeric selectivity."
        ),
        keywords=["polyolefin", "oligomers", "hydrocarbons", "enantiomeric"],
    ),
    StemBenchmarkSample(
        sample_id="stem-chem-002",
        domain="chemistry",
        text=(
            "Organometallic ruthenium phosphine complexes catalyze olefin metathesis "
            "with turnover frequencies exceeding 12000 per hour."
        ),
        keywords=["organometallic", "phosphine", "metathesis", "frequencies"],
    ),
    StemBenchmarkSample(
        sample_id="stem-bio-001",
        domain="biology",
        text=(
            "CRISPR-Cas9 ribonucleoprotein complexes mediate targeted double-strand "
            "endonuclease cleavage within mammalian epigenetic promoter loci."
        ),
        keywords=["ribonucleoprotein", "endonuclease", "epigenetic", "promoter"],
    ),
    StemBenchmarkSample(
        sample_id="stem-bio-002",
        domain="biology",
        text=(
            "G-protein coupled transmembrane receptors undergo conformational "
            "isomerization upon extracellular ligand phosphodiester binding."
        ),
        keywords=["transmembrane", "conformational", "isomerization", "phosphodiester"],
    ),
    StemBenchmarkSample(
        sample_id="stem-cs-001",
        domain="computer_science",
        text=(
            "Graph convolutional message-passing networks compute equivariant "
            "representations across heterogeneous distributed hypergraphs."
        ),
        keywords=["convolutional", "message-passing", "equivariant", "hypergraphs"],
    ),
    StemBenchmarkSample(
        sample_id="stem-cs-002",
        domain="computer_science",
        text=(
            "Static single assignment form optimizes register allocation and dead-code "
            "elimination via dominator tree depth-first traversal algorithms."
        ),
        keywords=["assignment", "optimization", "dominator", "algorithms"],
    ),
    StemBenchmarkSample(
        sample_id="stem-math-001",
        domain="mathematics",
        text=(
            "Cohomological operations on differentiable symplectic manifolds characterize "
            "topological invariants and compact Lagrangian submanifolds."
        ),
        keywords=["cohomological", "symplectic", "manifolds", "topological"],
    ),
    StemBenchmarkSample(
        sample_id="stem-math-002",
        domain="mathematics",
        text=(
            "The spectral radius of non-negative irreducible Perron-Frobenius operators "
            "dominates ergodic measure convergence in dynamical systems."
        ),
        keywords=["spectral", "irreducible", "Perron-Frobenius", "ergodic"],
    ),
]


DOMAIN_CORPUS_VOCABULARY_SEED: List[str] = [
    # Physics
    "quantum",
    "electrodynamics",
    "cavity",
    "optomechanics",
    "demonstrates",
    "photon",
    "phonon",
    "coupling",
    "cryogenic",
    "conditions",
    "resonance",
    "frequency",
    "majorana",
    "conductance",
    "anomalies",
    "superconductor",
    "semiconductor",
    "heterostructures",
    "non",
    "abelian",
    "topological",
    "phase",
    "transitions",
    # Chemistry
    "zeolite",
    "catalyzed",
    "cracking",
    "polyolefin",
    "oligomers",
    "yields",
    "octane",
    "branched",
    "hydrocarbons",
    "enantiomeric",
    "selectivity",
    "organometallic",
    "ruthenium",
    "phosphine",
    "complexes",
    "catalyze",
    "olefin",
    "metathesis",
    "turnover",
    "frequencies",
    "exceeding",
    # Biology
    "crispr",
    "cas9",
    "ribonucleoprotein",
    "mediate",
    "targeted",
    "double",
    "strand",
    "endonuclease",
    "cleavage",
    "mammalian",
    "epigenetic",
    "promoter",
    "loci",
    "protein",
    "coupled",
    "transmembrane",
    "receptors",
    "undergo",
    "conformational",
    "isomerization",
    "extracellular",
    "ligand",
    "phosphodiester",
    "binding",
    # Computer Science
    "graph",
    "convolutional",
    "message",
    "passing",
    "networks",
    "compute",
    "equivariant",
    "representations",
    "heterogeneous",
    "distributed",
    "hypergraphs",
    "static",
    "single",
    "assignment",
    "form",
    "optimizes",
    "register",
    "allocation",
    "dead",
    "code",
    "elimination",
    "dominator",
    "tree",
    "traversal",
    "algorithms",
    # Mathematics
    "cohomological",
    "operations",
    "differentiable",
    "symplectic",
    "manifolds",
    "characterize",
    "invariants",
    "compact",
    "lagrangian",
    "submanifolds",
    "spectral",
    "radius",
    "irreducible",
    "perron",
    "frobenius",
    "operators",
    "dominates",
    "ergodic",
    "measure",
    "convergence",
    "dynamical",
    "systems",
    # Subwords & suffixes
    "##ic",
    "##al",
    "##tion",
    "##ing",
    "##ed",
    "##es",
    "##s",
    "##ive",
    "##ity",
    "##ment",
    "##ly",
    "##able",
]


def get_stem_vocabulary_tokens() -> List[str]:
    """Generates a complete vocabulary list suitable for STEM benchmarks."""
    from laris.language.schemas import CANONICAL_SPECIAL_TOKENS

    tokens: List[str] = list(CANONICAL_SPECIAL_TOKENS)

    # Add single characters (ASCII printable)
    chars = [chr(i) for i in range(32, 127)]
    for ch in chars:
        if ch not in tokens:
            tokens.append(ch)

    # Greek alphabet
    for code in range(0x0370, 0x03FF):
        ch = chr(code)
        if ch not in tokens:
            tokens.append(ch)

    # Domain vocabulary seeds
    for word in DOMAIN_CORPUS_VOCABULARY_SEED:
        if word not in tokens:
            tokens.append(word)

    return tokens

