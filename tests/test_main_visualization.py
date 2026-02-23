from __future__ import annotations

import asyncio
import os
import unittest
from datetime import datetime, timedelta

from PyQt6.QtWidgets import QApplication

from main import MeetingTranslatorController
from overlay_ui import OverlayWindow


class VisualizationBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls._app = QApplication.instance() or QApplication([])

    def test_pending_fragment_emits_after_max_age(self) -> None:
        original = os.environ.get("MAX_PENDING_RENDER_AGE_SECONDS")
        original_min_emit = os.environ.get("MIN_EMIT_WORDS")
        os.environ["MAX_PENDING_RENDER_AGE_SECONDS"] = "0.2"
        os.environ["MIN_EMIT_WORDS"] = "3"
        loop = asyncio.new_event_loop()
        try:
            window = OverlayWindow()
            controller = MeetingTranslatorController(window, loop)
            controller._pending_render_text = "texto sin punto final"
            controller._pending_captured_at = datetime.now() - timedelta(seconds=0.4)
            self.assertTrue(controller._should_emit_pending("texto"))
            controller.shutdown_sync()
            window.close()
        finally:
            loop.close()
            if original is None:
                os.environ.pop("MAX_PENDING_RENDER_AGE_SECONDS", None)
            else:
                os.environ["MAX_PENDING_RENDER_AGE_SECONDS"] = original
            if original_min_emit is None:
                os.environ.pop("MIN_EMIT_WORDS", None)
            else:
                os.environ["MIN_EMIT_WORDS"] = original_min_emit

    def test_single_word_fragment_is_not_emitted_on_age_limit(self) -> None:
        original = os.environ.get("MAX_PENDING_RENDER_AGE_SECONDS")
        original_min_emit = os.environ.get("MIN_EMIT_WORDS")
        os.environ["MAX_PENDING_RENDER_AGE_SECONDS"] = "0.2"
        os.environ["MIN_EMIT_WORDS"] = "3"
        loop = asyncio.new_event_loop()
        try:
            window = OverlayWindow()
            controller = MeetingTranslatorController(window, loop)
            controller._pending_render_text = "you"
            controller._pending_captured_at = datetime.now() - timedelta(seconds=0.4)
            self.assertFalse(controller._should_emit_pending("you"))
            controller.shutdown_sync()
            window.close()
        finally:
            loop.close()
            if original is None:
                os.environ.pop("MAX_PENDING_RENDER_AGE_SECONDS", None)
            else:
                os.environ["MAX_PENDING_RENDER_AGE_SECONDS"] = original
            if original_min_emit is None:
                os.environ.pop("MIN_EMIT_WORDS", None)
            else:
                os.environ["MIN_EMIT_WORDS"] = original_min_emit

    def test_transcription_noise_cleaner_removes_promo_and_repeats(self) -> None:
        noisy = (
            "Aprende inglés gratis www. engvid. com por favor suscríbete al canal "
            "Preservar nombres, marcas, acrónimos, números y términos técnicos "
            "hola hola hola hola ysgrifennydd hola"
        )
        cleaned = MeetingTranslatorController._clean_transcription_noise(noisy)
        lowered = cleaned.lower()
        self.assertNotIn("engvid", lowered)
        self.assertNotIn("suscríbete", lowered)
        self.assertNotIn("preservar nombres", lowered)
        self.assertNotIn("ysgrifennydd", lowered)
        self.assertLessEqual(lowered.count("hola"), 3)


if __name__ == "__main__":
    unittest.main()
