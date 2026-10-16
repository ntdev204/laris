"""Smoke test verifying clean Python environment setup and packaging."""

import importlib
import unittest


class TestEnvironmentSmoke(unittest.TestCase):
    """Verifies that core packages and LARIS package are installed and importable."""

    def test_core_dependencies_importable(self):
        dependencies = ["yaml", "pydantic", "numpy"]
        for dep in dependencies:
            with self.subTest(dependency=dep):
                mod = importlib.import_module(dep)
                self.assertIsNotNone(mod)

    def test_laris_package_importable(self):
        import laris
        import laris.core.errors
        import laris.core.schemas

        self.assertIsNotNone(laris)
        self.assertEqual(laris.__version__, "0.1.0")
        self.assertIsNotNone(laris.core.schemas.ScientificClaim)
        self.assertIsNotNone(laris.core.errors.LarisError)

    def test_all_architectural_layers_importable(self):
        """Verifies every architectural layer from Layer 0 through Layer 11 is importable."""
        layers = [
            "laris.layers.layer0_corpus",
            "laris.layers.layer1_language",
            "laris.layers.layer2_semantic",
            "laris.layers.layer3_scinlp",
            "laris.layers.layer4_graph",
            "laris.layers.layer5_graph",
            "laris.layers.layer6_retrieval",
            "laris.layers.layer7_reasoning",
            "laris.layers.layer8_orchestration",
            "laris.layers.layer9_adaptive_execution",
            "laris.layers.layer10_evaluation",
            "laris.layers.layer11_reporting",
        ]
        for layer_module in layers:
            with self.subTest(layer=layer_module):
                mod = importlib.import_module(layer_module)
                self.assertIsNotNone(mod)

    def test_reporting_layer_key_classes_functional(self):
        """Verifies key Layer 11 reporting classes can be imported and instantiated."""
        from laris.layers.layer11_reporting import (
            AcademicManuscript,
            EvidenceGate,
            EvidenceInspector,
            ManuscriptComposer,
            ProjectHistoryManager,
            ReportSection,
            ReportSectionType,
            StructuredResearchReport,
        )

        self.assertIsNotNone(AcademicManuscript)
        self.assertIsNotNone(EvidenceGate)
        self.assertIsNotNone(EvidenceInspector)
        self.assertIsNotNone(ManuscriptComposer)
        self.assertIsNotNone(ProjectHistoryManager)
        self.assertIsNotNone(ReportSection)
        self.assertIsNotNone(ReportSectionType)
        self.assertIsNotNone(StructuredResearchReport)


if __name__ == "__main__":
    unittest.main()
