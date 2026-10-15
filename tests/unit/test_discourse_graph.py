"""Unit and integration tests for discourse graph parsing, ambiguity, and provenance.

Task ID: M3-SEM-002-SUB-02 (Issue #86)
Module ID: MOD-SEM-001 (Boundary C)
Governed by: ADR-002, ADR-004, and ADR-008.
"""

from laris.core.schemas import EvidenceCoordinate
from laris.layers.layer2_semantic import (
    CoreferenceCluster,
    CoreferenceOutput,
    CoreferenceResolutionStatus,
    DiscourseGraph,
    DiscourseGraphEdge,
    DiscourseRelationOutput,
    DiscourseRelationType,
    MentionSpan,
    ScientificDiscourseParser,
)


class TestDiscourseGraphAndProvenance:
    """Verifies multi-sentence discourse graph construction and provenance tracing."""

    def setup_method(self) -> None:
        self.parser = ScientificDiscourseParser()

    def test_multi_sentence_discourse_graph_construction(self) -> None:
        coord1 = EvidenceCoordinate(
            coordinate_id="COORD-GRAPH-01",
            document_id="DOC-MET-01",
            document_sha256="c" * 64,
            page_number=3,
            section_identifier="results",
            paragraph_index=2,
            sentence_index=1,
            char_start=0,
            char_end=60,
            verbatim_snippet="Addition of dopant X caused lattice expansion.",
        )
        coord2 = EvidenceCoordinate(
            coordinate_id="COORD-GRAPH-02",
            document_id="DOC-MET-01",
            document_sha256="c" * 64,
            page_number=3,
            section_identifier="results",
            paragraph_index=2,
            sentence_index=2,
            char_start=61,
            char_end=130,
            verbatim_snippet="In contrast, dopant Y induced no detectable lattice expansion.",
        )

        r1 = self.parser.parse_pair(
            arg1="Addition of dopant X was performed.",
            arg2="Addition of dopant X caused lattice expansion.",
            relation_id="REL-G-1",
            causal_verified=True,
            evidence_coordinate=coord1,
        )
        r2 = self.parser.parse_pair(
            arg1="Addition of dopant X caused lattice expansion.",
            arg2="In contrast, dopant Y induced no detectable lattice expansion.",
            relation_id="REL-G-2",
            evidence_coordinate=coord2,
        )

        graph = DiscourseGraph(document_id="DOC-MET-01")
        graph.add_edge(
            DiscourseGraphEdge(
                edge_id="EDGE-1",
                source_sentence_id="S1",
                target_sentence_id="S2",
                relation=r1,
            )
        )
        graph.add_edge(
            DiscourseGraphEdge(
                edge_id="EDGE-2",
                source_sentence_id="S2",
                target_sentence_id="S3",
                relation=r2,
            )
        )

        assert len(graph.edges) == 2
        assert r1.relation_type == DiscourseRelationType.CAUSAL
        assert r2.relation_type == DiscourseRelationType.CONTRAST

        # Trace provenance coordinates across graph
        coords = graph.trace_provenance()
        assert len(coords) == 2
        assert coords[0].coordinate_id == "COORD-GRAPH-01"
        assert coords[1].coordinate_id == "COORD-GRAPH-02"

        # Edge serialization round-trip
        e_dict = graph.edges[0].to_dict()
        restored_edge = DiscourseGraphEdge.from_dict(e_dict)
        assert restored_edge.edge_id == "EDGE-1"
        assert restored_edge.relation.relation_id == "REL-G-1"

    def test_causal_chains_extraction(self) -> None:
        """Extract multi-step verified causal paths."""
        r1 = DiscourseRelationOutput(
            relation_id="REL-C1",
            relation_type=DiscourseRelationType.CAUSAL,
            arg1="Temperature decreased below critical threshold.",
            arg2="Resistance dropped to zero.",
            connective_cue="caused",
            causal_verified=True,
        )
        r2 = DiscourseRelationOutput(
            relation_id="REL-C2",
            relation_type=DiscourseRelationType.CAUSAL,
            arg1="Resistance dropped to zero.",
            arg2="Persistent screening currents circulated.",
            connective_cue="led to",
            causal_verified=True,
        )
        r3 = DiscourseRelationOutput(
            relation_id="REL-NC",
            relation_type=DiscourseRelationType.TEMPORAL,
            arg1="Persistent screening currents circulated.",
            arg2="Subsequently, measurements were logged.",
            connective_cue="subsequently",
        )

        graph = DiscourseGraph(document_id="DOC-SC-01")
        graph.add_edge(DiscourseGraphEdge("E1", "S1", "S2", r1))
        graph.add_edge(DiscourseGraphEdge("E2", "S2", "S3", r2))
        graph.add_edge(DiscourseGraphEdge("E3", "S3", "S4", r3))

        causal_chains = graph.get_causal_chains()
        assert len(causal_chains) == 1
        assert causal_chains[0] == ["S1", "S2", "S3"]

        temporal_edges = graph.get_edges_by_type(DiscourseRelationType.TEMPORAL)
        assert len(temporal_edges) == 1
        assert temporal_edges[0].edge_id == "E3"


class TestDiscourseAmbiguityAndUnknownStates:
    """Verifies handling of ambiguous, conflicting, and unknown discourse relations."""

    def setup_method(self) -> None:
        self.parser = ScientificDiscourseParser()

    def test_conflicting_connectives_yield_ambiguous_state(self) -> None:
        arg1 = "The trial proceeded according to protocol."
        arg2 = "However, although preliminary signals were noted, endpoints diverged."

        out = self.parser.parse_pair(arg1, arg2, relation_id="REL-AMBIG-01")
        assert out.relation_type == DiscourseRelationType.AMBIGUOUS
        assert out.uncertainty_score >= 0.80

    def test_unknown_relation_handling_without_recognized_cues(self) -> None:
        arg1 = "The specimen was dried under vacuum."
        arg2 = "Spectroscopic analysis was performed."

        out = self.parser.parse_pair(arg1, arg2, relation_id="REL-UNK-01")
        assert out.relation_type == DiscourseRelationType.UNKNOWN_RELATION
        assert out.uncertainty_score >= 0.90
        assert out.connective_cue is None


class TestCoreferenceAmbiguityAndProvenance:
    """Verifies coreference clusters with ambiguous antecedents, singletons,
    and coordinate provenance.
    """

    def test_ambiguous_antecedent_coreference(self) -> None:
        coord = EvidenceCoordinate(
            coordinate_id="COORD-COREF-01",
            document_id="DOC-BIO-01",
            document_sha256="d" * 64,
            page_number=5,
            section_identifier="discussion",
            paragraph_index=3,
            sentence_index=2,
            char_start=12,
            char_end=48,
            verbatim_snippet="Both kinase A and kinase B phosphorylated the substrate.",
        )
        m1 = MentionSpan("M-K1", "kinase A", start_char=5, end_char=13, evidence_coordinate=coord)
        m2 = MentionSpan("M-K2", "kinase B", start_char=18, end_char=26, evidence_coordinate=coord)
        m_pronoun = MentionSpan("M-PRO", "it", start_char=75, end_char=77)

        cluster = CoreferenceCluster(
            cluster_id="CLUST-AMBIG-KINASE",
            canonical_mention="kinase (ambiguous antecedent)",
            mentions=[m1, m2, m_pronoun],
            confidence=0.40,
            status=CoreferenceResolutionStatus.AMBIGUOUS_ANTECEDENT,
        )
        assert cluster.status == CoreferenceResolutionStatus.AMBIGUOUS_ANTECEDENT
        assert cluster.confidence < 0.50

    def test_unresolved_singletons_in_coreference_output(self) -> None:
        singleton = MentionSpan(
            mention_id="M-SINGLETON",
            text="an uncharacterized hypothetical protein",
            start_char=200,
            end_char=240,
        )
        output = CoreferenceOutput(
            clusters=[],
            unresolved_mentions=[singleton],
            document_id="DOC-BIO-01",
        )
        assert len(output.clusters) == 0
        assert len(output.unresolved_mentions) == 1
        assert output.unresolved_mentions[0].mention_id == "M-SINGLETON"


def test_discourse_parser_all_cue_types() -> None:
    parser = ScientificDiscourseParser()

    # Correlational cue
    out_corr = parser.parse_pair(
        "Biomarker X levels increased.",
        "This trend was correlated with disease progression.",
        relation_id="R-CORR",
    )
    assert out_corr.relation_type == DiscourseRelationType.CORRELATIONAL

    # Concessive cue alone
    out_conc = parser.parse_pair(
        "The reaction was expected to stop.",
        "Although thermal dissipation was high, catalysis continued.",
        relation_id="R-CONC",
    )
    assert out_conc.relation_type == DiscourseRelationType.CONCESSIVE

    # Temporal cue
    out_temp = parser.parse_pair(
        "The alloy was forged at 1200 C.",
        "Subsequently, cryogenic annealing was conducted.",
        relation_id="R-TEMP",
    )
    assert out_temp.relation_type == DiscourseRelationType.TEMPORAL

    # Elaboration cue
    out_elab = parser.parse_pair(
        "The synthesis protocol was modified.",
        "Specifically, solvent polarity was adjusted to 0.85.",
        relation_id="R-ELAB",
    )
    assert out_elab.relation_type == DiscourseRelationType.ELABORATION

    # Verified causal cue
    out_causal = parser.parse_pair(
        "CRISPR deletion was induced.",
        "The knockout caused complete silencing of the promoter.",
        relation_id="R-CAUSAL",
        causal_verified=True,
    )
    assert out_causal.relation_type == DiscourseRelationType.CAUSAL
    assert out_causal.causal_verified is True
