from __future__ import annotations

import unittest

from translation_service import TechnicalTranslationService


class LooksSpanishTests(unittest.TestCase):
    def test_requires_at_least_four_markers(self) -> None:
        self.assertFalse(TechnicalTranslationService._looks_spanish("el sistema y control en"))
        self.assertTrue(TechnicalTranslationService._looks_spanish("el sistema y control en la red"))

    def test_repairs_common_english_residuals_for_spanish(self) -> None:
        repaired = TechnicalTranslationService._repair_spanish_residual_english("You model with code and tests")
        self.assertEqual(repaired, "tú modelo con código y tests")


if __name__ == "__main__":
    unittest.main()
