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
        asyncio.set_event_loop(loop)
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
        asyncio.set_event_loop(loop)
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

    def test_stale_segment_is_dropped_before_render(self) -> None:
        original_stale = os.environ.get("MAX_SEGMENT_STALENESS_SECONDS")
        os.environ["MAX_SEGMENT_STALENESS_SECONDS"] = "0.2"
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            window = OverlayWindow()
            controller = MeetingTranslatorController(window, loop)
            old_capture = datetime.now() - timedelta(seconds=15.0)
            controller._emit_segment("texto tardío", old_capture, "en", api_time=0.3, metrics_data={})
            self.assertEqual(window.get_full_transcript_text(), "")
            self.assertEqual(controller.skipped_stale_segments, 1)
            controller.shutdown_sync()
            window.close()
        finally:
            loop.close()
            if original_stale is None:
                os.environ.pop("MAX_SEGMENT_STALENESS_SECONDS", None)
            else:
                os.environ["MAX_SEGMENT_STALENESS_SECONDS"] = original_stale

    def test_moderately_stale_segment_is_rendered_when_backlog_is_empty(self) -> None:
        original_stale = os.environ.get("MAX_SEGMENT_STALENESS_SECONDS")
        os.environ["MAX_SEGMENT_STALENESS_SECONDS"] = "1.0"
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            window = OverlayWindow()
            controller = MeetingTranslatorController(window, loop)
            old_capture = datetime.now() - timedelta(seconds=1.5)
            controller._emit_segment("texto tardio pero util", old_capture, "en", api_time=0.3, metrics_data={})
            self.assertIn("texto tardio pero util", window.get_full_transcript_text())
            self.assertEqual(controller.skipped_stale_segments, 0)
            controller.shutdown_sync()
            window.close()
        finally:
            loop.close()
            if original_stale is None:
                os.environ.pop("MAX_SEGMENT_STALENESS_SECONDS", None)
            else:
                os.environ["MAX_SEGMENT_STALENESS_SECONDS"] = original_stale

    def test_first_emit_can_flush_single_long_word_after_age_limit(self) -> None:
        original_age = os.environ.get("MAX_PENDING_RENDER_AGE_SECONDS")
        os.environ["MAX_PENDING_RENDER_AGE_SECONDS"] = "0.2"
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            window = OverlayWindow()
            controller = MeetingTranslatorController(window, loop)
            controller._pending_render_text = "funciona"
            controller._pending_captured_at = datetime.now() - timedelta(seconds=0.4)
            self.assertTrue(controller._should_emit_pending("funciona"))
            controller.shutdown_sync()
            window.close()
        finally:
            loop.close()
            if original_age is None:
                os.environ.pop("MAX_PENDING_RENDER_AGE_SECONDS", None)
            else:
                os.environ["MAX_PENDING_RENDER_AGE_SECONDS"] = original_age

    def test_pending_fragment_emits_earlier_when_source_preview_is_active(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            window = OverlayWindow()
            controller = MeetingTranslatorController(window, loop)
            controller._source_preview_active = True
            controller._pending_render_text = "texto breve"
            controller._pending_captured_at = datetime.now()
            self.assertTrue(controller._should_emit_pending("texto breve"))
            controller.shutdown_sync()
            window.close()
        finally:
            loop.close()

    def test_source_buffer_waits_on_trailing_connector(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            window = OverlayWindow()
            controller = MeetingTranslatorController(window, loop)
            controller._buffer_source_fragment(
                "more quickly and",
                chunk_captured_at=datetime.now(),
                source_language="en",
                metrics_data={
                    "captured_at": datetime.now(),
                    "source_language": "en",
                    "transcription_start_ts": datetime.now(),
                    "transcription_end_ts": datetime.now(),
                    "translation_start_ts": datetime.now(),
                    "translation_end_ts": datetime.now(),
                    "transcription_time_s": 0.4,
                    "translation_time_s": 0.0,
                    "audio_backlog": 0,
                    "text_backlog": 0,
                    "had_fallback": False,
                    "fallback_reason": "",
                },
            )
            self.assertFalse(controller._should_translate_pending_source("more quickly and", backlog=0, audio_backlog=0))
            controller.shutdown_sync()
            window.close()
        finally:
            loop.close()

    def test_source_buffer_forces_translation_under_backlog(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            window = OverlayWindow()
            controller = MeetingTranslatorController(window, loop)
            controller._buffer_source_fragment(
                "take action",
                chunk_captured_at=datetime.now(),
                source_language="en",
                metrics_data={
                    "captured_at": datetime.now(),
                    "source_language": "en",
                    "transcription_start_ts": datetime.now(),
                    "transcription_end_ts": datetime.now(),
                    "translation_start_ts": datetime.now(),
                    "translation_end_ts": datetime.now(),
                    "transcription_time_s": 0.4,
                    "translation_time_s": 0.0,
                    "audio_backlog": 1,
                    "text_backlog": 1,
                    "had_fallback": False,
                    "fallback_reason": "",
                },
            )
            self.assertTrue(controller._should_translate_pending_source("take action", backlog=1, audio_backlog=1))
            controller.shutdown_sync()
            window.close()
        finally:
            loop.close()

    def test_first_translation_flushes_early_without_waiting_second_chunk(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            window = OverlayWindow()
            controller = MeetingTranslatorController(window, loop)
            controller._buffer_source_fragment(
                "take action",
                chunk_captured_at=datetime.now() - timedelta(seconds=0.35),
                source_language="en",
                metrics_data={
                    "captured_at": datetime.now(),
                    "source_language": "en",
                    "transcription_start_ts": datetime.now(),
                    "transcription_end_ts": datetime.now(),
                    "translation_start_ts": datetime.now(),
                    "translation_end_ts": datetime.now(),
                    "transcription_time_s": 0.4,
                    "translation_time_s": 0.0,
                    "audio_backlog": 0,
                    "text_backlog": 0,
                    "had_fallback": False,
                    "fallback_reason": "",
                },
            )
            self.assertTrue(controller._should_translate_pending_source("take action", backlog=0, audio_backlog=0))
            controller.shutdown_sync()
            window.close()
        finally:
            loop.close()

    def test_source_buffer_flushes_after_two_fragments_when_tail_is_stable(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            window = OverlayWindow()
            controller = MeetingTranslatorController(window, loop)
            now = datetime.now()
            base_metrics = {
                "captured_at": now,
                "source_language": "en",
                "transcription_start_ts": now,
                "transcription_end_ts": now,
                "translation_start_ts": now,
                "translation_end_ts": now,
                "transcription_time_s": 0.4,
                "translation_time_s": 0.0,
                "audio_backlog": 0,
                "text_backlog": 0,
                "had_fallback": False,
                "fallback_reason": "",
            }
            controller._buffer_source_fragment(
                "they move faster",
                chunk_captured_at=now - timedelta(seconds=0.5),
                source_language="en",
                metrics_data=base_metrics,
            )
            controller._buffer_source_fragment(
                "with better memory",
                chunk_captured_at=now - timedelta(seconds=0.2),
                source_language="en",
                metrics_data=base_metrics,
            )
            self.assertTrue(
                controller._should_translate_pending_source("with better memory", backlog=0, audio_backlog=0)
            )
            controller.shutdown_sync()
            window.close()
        finally:
            loop.close()


if __name__ == "__main__":
    unittest.main()
