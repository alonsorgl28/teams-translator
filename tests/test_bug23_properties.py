from __future__ import annotations

import unittest

from hypothesis import given, settings, strategies as st

from segment_quality import SegmentQualityGate


class Bug23PropertyTests(unittest.TestCase):
    @settings(max_examples=40, deadline=None)
    @given(st.text(alphabet=st.characters(min_codepoint=0x4E00, max_codepoint=0x9FFF), min_size=1, max_size=8))
    def test_commit_never_accepts_disallowed_script_for_spanish(self, script_text: str) -> None:
        gate = SegmentQualityGate()
        decision = gate.decide_commit(
            source_text="this is a complete english source sentence",
            translated_text=f"hola {script_text} mundo",
            target_language="Spanish",
            route="normal",
            pending_age_s=1.0,
        )
        self.assertEqual(decision.stage, "drop")
        self.assertEqual(decision.dropped_reason, "language_guard")

    @settings(max_examples=40, deadline=None)
    @given(
        st.lists(
            st.sampled_from(["this", "is", "a", "model", "comparison", "with", "more", "detail"]),
            min_size=4,
            max_size=8,
        )
    )
    def test_commit_never_allows_english_passthrough_for_spanish(self, tokens: list[str]) -> None:
        gate = SegmentQualityGate()
        source = " ".join(tokens)
        decision = gate.decide_commit(
            source_text=source,
            translated_text=source,
            target_language="Spanish",
            route="normal",
            pending_age_s=1.0,
        )
        self.assertEqual(decision.stage, "drop")
        self.assertIn(decision.dropped_reason, {"translation_too_similar", "language_guard", "source_low_confidence"})

    @settings(max_examples=40, deadline=None)
    @given(
        st.lists(
            st.sampled_from(["the", "model", "with", "code", "for", "tests"]),
            min_size=2,
            max_size=4,
        )
    )
    def test_short_incomplete_source_is_not_committed(self, tokens: list[str]) -> None:
        gate = SegmentQualityGate()
        source = " ".join(tokens)
        decision = gate.decide_commit(
            source_text=source,
            translated_text="traducción aparentemente válida",
            target_language="Spanish",
            route="normal",
            pending_age_s=0.7,
        )
        self.assertEqual(decision.stage, "drop")
        self.assertIn(decision.dropped_reason, {"source_low_confidence", "commit_too_short"})


if __name__ == "__main__":
    unittest.main()
