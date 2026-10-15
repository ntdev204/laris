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
        self.assertIsNotNone(laris.core.schemas.ScientificClaim)
        self.assertIsNotNone(laris.core.errors.LarisError)


if __name__ == "__main__":
    unittest.main()
