from __future__ import annotations

import unittest

from segment_quality import SegmentQualityGate


class SegmentQualityGateTests(unittest.TestCase):
    def test_preview_drops_non_latin_script_for_spanish(self) -> None:
        gate = SegmentQualityGate()
        decision = gate.decide_preview(
            source_text="this is a test",
            translated_text="hola 你好 mundo",
            target_language="Spanish",
            route="normal",
            pending_age_s=0.6,
        )
        self.assertEqual(decision.stage, "drop")
        self.assertEqual(decision.dropped_reason, "language_guard")

    def test_commit_drops_single_word(self) -> None:
        gate = SegmentQualityGate()
        decision = gate.decide_commit(
            source_text="this is a longer phrase",
            translated_text="hola",
            target_language="Spanish",
            route="normal",
            pending_age_s=0.5,
        )
        self.assertEqual(decision.stage, "drop")
        self.assertEqual(decision.dropped_reason, "single_word_final")

    def test_confidence_improves_with_complete_source(self) -> None:
        gate = SegmentQualityGate()
        short = gate.confidence_from_source("and")
        long_sentence = gate.confidence_from_source("this is a complete sentence about power systems.")
        self.assertLess(short, long_sentence)

    def test_commit_drops_reject_phrase(self) -> None:
        gate = SegmentQualityGate()
        decision = gate.decide_commit(
            source_text="any source",
            translated_text="Lo siento, no puedo ayudar con eso.",
            target_language="Spanish",
            route="normal",
            pending_age_s=0.6,
        )
        self.assertEqual(decision.stage, "drop")
        self.assertEqual(decision.dropped_reason, "reject_phrase")

    def test_commit_drops_low_confidence_source_before_final_render(self) -> None:
        gate = SegmentQualityGate()
        decision = gate.decide_commit(
            source_text="The substation I'm Grady",
            translated_text="La subestación soy Grady",
            target_language="Spanish",
            route="normal",
            pending_age_s=0.6,
        )
        self.assertEqual(decision.stage, "drop")
        self.assertEqual(decision.dropped_reason, "source_low_confidence")

    def test_commit_drops_translation_too_similar_to_source(self) -> None:
        gate = SegmentQualityGate()
        decision = gate.decide_commit(
            source_text="this is a model comparison with more detail",
            translated_text="this is a model comparison with more detail",
            target_language="Spanish",
            route="normal",
            pending_age_s=0.8,
        )
        self.assertEqual(decision.stage, "drop")
        self.assertIn(decision.dropped_reason, {"translation_too_similar", "language_guard"})


if __name__ == "__main__":
    unittest.main()
