"""Documentation quality gate test integrated with unittest."""

import unittest

from scripts.validate_docs import validate_all_docs


class TestDocumentationQualityGate(unittest.TestCase):
    """Executes documentation validation as a regression test."""

    def test_all_documentation_passes_quality_gate(self):
        errors, warnings, count = validate_all_docs()
        self.assertGreater(count, 0, "Should have validated at least one documentation file.")
        self.assertEqual(len(errors), 0, f"Documentation validation failed with errors: {errors}")


if __name__ == "__main__":
    unittest.main()
