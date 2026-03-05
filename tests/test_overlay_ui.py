from __future__ import annotations

import os
import unittest

from PyQt6.QtCore import Qt
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

    def test_subtitle_font_is_clamped_for_readability(self) -> None:
        original = os.environ.get("SUBTITLE_FONT_SIZE")
        os.environ["SUBTITLE_FONT_SIZE"] = "72"
        try:
            window = OverlayWindow()
            self.assertLessEqual(window.subtitle_curr_label.font().pointSize(), 23)
            self.assertGreaterEqual(window.subtitle_curr_label.font().pointSize(), 18)
            window.close()
        finally:
            if original is None:
                os.environ.pop("SUBTITLE_FONT_SIZE", None)
            else:
                os.environ["SUBTITLE_FONT_SIZE"] = original

    def test_window_keeps_regular_window_flag_instead_of_tool(self) -> None:
        window = OverlayWindow()
        flags = window.windowFlags()
        self.assertTrue(bool(flags & Qt.WindowType.Window))
        self.assertFalse(bool(flags & Qt.WindowType.Tool))
        window.close()

    def test_buttons_do_not_take_focus_ring(self) -> None:
        window = OverlayWindow()
        self.assertEqual(window.stop_button.focusPolicy(), Qt.FocusPolicy.NoFocus)
        self.assertEqual(window.start_stop_button.focusPolicy(), Qt.FocusPolicy.NoFocus)
        self.assertEqual(window.close_button.focusPolicy(), Qt.FocusPolicy.NoFocus)
        window.close()

    def test_subtitle_box_height_reduced(self) -> None:
        window = OverlayWindow()
        self.assertEqual(window.subtitle_box.minimumHeight(), 132)
        self.assertFalse(hasattr(window, "resize_grip"))
        window.close()

    def test_live_tools_panel_starts_closed_even_with_debug_enabled(self) -> None:
        original_debug = os.environ.get("DEBUG_MODE")
        os.environ["DEBUG_MODE"] = "1"
        try:
            window = OverlayWindow()
            window.set_listening(True)
            self.assertFalse(window.tools_frame.isVisible())
            window.close()
        finally:
            if original_debug is None:
                os.environ.pop("DEBUG_MODE", None)
            else:
                os.environ["DEBUG_MODE"] = original_debug

    def test_live_preview_renders_without_appending_history(self) -> None:
        original_mode = os.environ.get("SUBTITLE_MODE")
        os.environ["SUBTITLE_MODE"] = "cinema"
        try:
            window = OverlayWindow()
            window.set_listening(True)
            window.set_live_preview("preview text")
            self.assertEqual(window.subtitle_curr_label.text(), "preview text")
            self.assertEqual(window.get_full_transcript_text(), "")
            window.clear_live_preview()
            self.assertEqual(window.subtitle_curr_label.text(), "")
            window.close()
        finally:
            if original_mode is None:
                os.environ.pop("SUBTITLE_MODE", None)
            else:
                os.environ["SUBTITLE_MODE"] = original_mode


if __name__ == "__main__":
    unittest.main()
