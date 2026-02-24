from __future__ import annotations

import os
import unittest

from PyQt6.QtWidgets import QApplication

from overlay_ui import OverlayWindow


class OverlayBufferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls._app = QApplication.instance() or QApplication([])

    def test_full_transcript_buffer_is_bounded(self) -> None:
        original = os.environ.get("FULL_TRANSCRIPT_MAX_SEGMENTS")
        os.environ["FULL_TRANSCRIPT_MAX_SEGMENTS"] = "3"
        try:
            window = OverlayWindow()
            for idx in range(1, 5):
                window.append_segment(f"[00:0{idx}] line {idx}")

            self.assertEqual(len(window.full_transcript_buffer), 3)
            self.assertEqual(
                list(window.full_transcript_buffer),
                ["[00:02] line 2", "[00:03] line 3", "[00:04] line 4"],
            )
            window.close()
        finally:
            if original is None:
                os.environ.pop("FULL_TRANSCRIPT_MAX_SEGMENTS", None)
            else:
                os.environ["FULL_TRANSCRIPT_MAX_SEGMENTS"] = original

    def test_cinema_mode_toggles_visible_subtitles(self) -> None:
        original_mode = os.environ.get("SUBTITLE_MODE")
        os.environ["SUBTITLE_MODE"] = "cinema"
        try:
            window = OverlayWindow()
            self.assertTrue(window.subtitle_box.isHidden())
            self.assertTrue(window.transcript_view.isHidden())

            window._on_start_stop_clicked()
            self.assertFalse(window.subtitle_box.isHidden())
            self.assertTrue(window.transcript_view.isHidden())

            window.append_segment("[00:01] hola mundo")
            window._flush_cinema_text()
            self.assertIn("hola mundo", window.subtitle_curr_label.text())

            window._on_start_stop_clicked()
            self.assertTrue(window.subtitle_box.isHidden())
            self.assertTrue(window.transcript_view.isHidden())
            window.close()
        finally:
            if original_mode is None:
                os.environ.pop("SUBTITLE_MODE", None)
            else:
                os.environ["SUBTITLE_MODE"] = original_mode


if __name__ == "__main__":
    unittest.main()
