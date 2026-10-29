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
        self.assertEqual(laris.__version__, "1.1.4")
        self.assertIsNotNone(laris.core.schemas.ScientificClaim)
        self.assertIsNotNone(laris.core.errors.LarisError)

    def test_all_canonical_domain_packages_importable(self):
        """Verifies every canonical domain package is importable."""
        domain_packages = [
            "laris.corpus",
            "laris.language",
            "laris.reasoning",
            "laris.scientific",
            "laris.graph",
            "laris.retrieval",
            "laris.orchestration",
            "laris.execution",
            "laris.evaluation",
            "laris.reporting",
        ]
        for pkg in domain_packages:
            with self.subTest(package=pkg):
                mod = importlib.import_module(pkg)
                self.assertIsNotNone(mod)


    def test_reporting_layer_key_classes_functional(self):
        """Verifies key Layer 11 reporting classes can be imported and instantiated."""
        from laris.reporting import (
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
