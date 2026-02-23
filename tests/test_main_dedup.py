from __future__ import annotations

import asyncio
import os
import unittest

from PyQt6.QtWidgets import QApplication

from main import MeetingTranslatorController
from overlay_ui import OverlayWindow


class DuplicateDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls._app = QApplication.instance() or QApplication([])

    def test_word_order_change_is_not_duplicate(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            window = OverlayWindow()
            controller = MeetingTranslatorController(window, loop)
            self.assertFalse(controller._is_duplicate_segment("[00:01] El conductor de la red electrica"))
            self.assertFalse(controller._is_duplicate_segment("[00:02] La red electrica del conductor"))
            controller.shutdown_sync()
            window.close()
        finally:
            loop.close()


if __name__ == "__main__":
    unittest.main()
