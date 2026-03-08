from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from translation_service import TechnicalTranslationService


class LooksSpanishTests(unittest.TestCase):
    def test_requires_at_least_four_markers(self) -> None:
        self.assertFalse(TechnicalTranslationService._looks_spanish("el sistema y control en"))
        self.assertTrue(TechnicalTranslationService._looks_spanish("el sistema y control en la red"))

    def test_repairs_common_english_residuals_for_spanish(self) -> None:
        repaired = TechnicalTranslationService._repair_spanish_residual_english("You model with code and tests")
        self.assertEqual(repaired, "tú modelo con código y tests")

    def test_short_fragments_skip_context(self) -> None:
        self.assertFalse(TechnicalTranslationService._should_use_context("short fragment"))
        self.assertFalse(
            TechnicalTranslationService._should_use_context(
                "this is a fragment with enough words to use stable translation context"
            )
        )
        self.assertTrue(
            TechnicalTranslationService._should_use_context(
                "this is a stable sentence with enough words to use stable translation context."
            )
        )

    def test_incomplete_fragment_prefers_literal_translation(self) -> None:
        self.assertTrue(TechnicalTranslationService._should_force_literal_translation("more quickly and"))
        self.assertTrue(TechnicalTranslationService._looks_incomplete_fragment("with the"))
        self.assertFalse(TechnicalTranslationService._looks_incomplete_fragment("this is a stable sentence."))

    def test_reset_context_clears_internal_memory(self) -> None:
        service = object.__new__(TechnicalTranslationService)
        service._recent_source = MagicMock()
        service._recent_translations = MagicMock()
        service._session_terms = {"model": 2}
        service.last_error = "boom"
        service.reset_context()
        service._recent_source.clear.assert_called_once()
        service._recent_translations.clear.assert_called_once()
        self.assertEqual(service._session_terms, {})
        self.assertIsNone(service.last_error)

    def test_incomplete_fragments_are_not_remembered(self) -> None:
        service = object.__new__(TechnicalTranslationService)
        service._context_enabled = True
        service._glossary_enabled = True
        service._recent_source = []
        service._recent_translations = []
        service._session_terms = {}
        service._term_memory_size = 24
        service._term_min_count = 2
        service.last_error = None
        service._remember_turn("more quickly and", "más rápido y")
        self.assertEqual(service._recent_source, [])
        self.assertEqual(service._recent_translations, [])
        self.assertEqual(service._session_terms, {})

    def test_detects_non_spanish_output_when_cjk_present(self) -> None:
        self.assertTrue(TechnicalTranslationService._looks_non_spanish_output("这是一个测试"))
        self.assertTrue(TechnicalTranslationService._looks_non_spanish_output("hola 你好 mundo"))

    def test_detects_non_spanish_output_when_english_function_words_dominate(self) -> None:
        self.assertTrue(
            TechnicalTranslationService._looks_non_spanish_output(
                "this is the model and it is running in the system"
            )
        )
        self.assertFalse(
            TechnicalTranslationService._looks_non_spanish_output(
                "este es el modelo y está corriendo en el sistema"
            )
        )

    def test_flags_output_too_similar_to_source_without_spanish_markers(self) -> None:
        self.assertTrue(
            TechnicalTranslationService._looks_too_similar_to_source(
                "which model is better codex",
                "wich model is beter codex",
            )
        )
        self.assertFalse(
            TechnicalTranslationService._looks_too_similar_to_source(
                "which model is better codex",
                "qué modelo es mejor codex",
            )
        )

    def test_select_route_uses_premium_for_low_confidence_when_ratio_allows(self) -> None:
        service = object.__new__(TechnicalTranslationService)
        service._premium_model = "gpt-4o"
        service._premium_trigger_score = 0.82
        service._premium_max_ratio = 0.25
        service._segments_routed = 4
        service._premium_segments = 0
        route = service._select_route(0.4, force_premium=False)
        self.assertEqual(route, "premium")

    def test_select_route_blocks_premium_when_ratio_reached(self) -> None:
        service = object.__new__(TechnicalTranslationService)
        service._premium_model = "gpt-4o"
        service._premium_trigger_score = 0.82
        service._premium_max_ratio = 0.25
        service._segments_routed = 4
        service._premium_segments = 1
        route = service._select_route(0.3, force_premium=False)
        self.assertEqual(route, "normal")

    def test_apply_domain_glossary_replaces_matched_terms_for_spanish(self) -> None:
        output = TechnicalTranslationService._apply_domain_glossary(
            source_text="Check the insulator and bushing in the transformer",
            translated_text="Verifica el insulator y el bushing del transformador",
            target_language="Spanish",
            domain_glossary=[
                {"term_en": "insulator", "term_es": "aislador", "rule": "translate"},
                {"term_en": "bushing", "term_es": "boquilla", "rule": "translate"},
            ],
        )
        self.assertIn("aislador", output)
        self.assertIn("boquilla", output)


if __name__ == "__main__":
    unittest.main()
