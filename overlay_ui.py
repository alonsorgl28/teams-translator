from __future__ import annotations

import os
import threading
from collections import deque
from typing import Optional

from PyQt6.QtCore import QPoint, QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPixmap, QShortcut, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from audio_listener import SystemAudioListener
from config_utils import read_bool_env, read_int_env


class SettingsDialog(QDialog):
    DEFAULT_LANG_OPTIONS = (
        "Auto-detect",
        "English",
        "Spanish",
        "Portuguese (Brazil)",
        "Mandarin Chinese (Simplified)",
        "Hindi",
    )
    DEFAULT_TARGET_OPTIONS = (
        "Spanish",
        "English",
        "Portuguese (Brazil)",
        "Mandarin Chinese (Simplified)",
        "Hindi",
    )

    def __init__(
        self,
        brand_name: str,
        source_language: str,
        target_language: str,
        audio_source: str,
        audio_sources: list[str],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._brand_name = brand_name
        self._audio_sources = audio_sources or ["System loopback (default)"]
        self.setWindowTitle(f"{self._brand_name} Settings")
        self.setModal(True)
        self.setFixedWidth(480)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(20)

        # ── Languages card ──
        lang_card = QFrame()
        lang_card.setObjectName("settingsCard")
        lang_card_layout = QVBoxLayout(lang_card)
        lang_card_layout.setContentsMargins(18, 16, 18, 16)
        lang_card_layout.setSpacing(14)

        lang_header = QLabel("LANGUAGES")
        lang_header.setObjectName("cardHeader")
        lang_header.setFont(self._make_ui_font(11))
        lang_card_layout.addWidget(lang_header)

        lang_row = QHBoxLayout()
        lang_row.setSpacing(14)
        lang_card_layout.addLayout(lang_row)

        left_lang = QVBoxLayout()
        left_lang.setSpacing(5)
        lang_row.addLayout(left_lang)
        from_label = QLabel("From")
        from_label.setObjectName("fieldLabel")
        from_label.setFont(self._make_ui_font(11))
        left_lang.addWidget(from_label)
        self.from_combo = QComboBox()
        self.from_combo.addItems(self.DEFAULT_LANG_OPTIONS)
        self._set_combo_value(self.from_combo, source_language, default="Auto-detect")
        left_lang.addWidget(self.from_combo)

        arrow_label = QLabel("\u2192")
        arrow_label.setObjectName("arrowLabel")
        arrow_label.setFont(self._make_ui_font(16))
        arrow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        arrow_label.setFixedWidth(28)
        lang_row.addWidget(arrow_label, alignment=Qt.AlignmentFlag.AlignBottom)

        right_lang = QVBoxLayout()
        right_lang.setSpacing(5)
        lang_row.addLayout(right_lang)
        to_label = QLabel("To")
        to_label.setObjectName("fieldLabel")
        to_label.setFont(self._make_ui_font(11))
        right_lang.addWidget(to_label)
        self.to_combo = QComboBox()
        self.to_combo.addItems(self.DEFAULT_TARGET_OPTIONS)
        self._set_combo_value(self.to_combo, target_language, default="Spanish")
        right_lang.addWidget(self.to_combo)

        root.addWidget(lang_card)

        # ── Audio Source card ──
        audio_card = QFrame()
        audio_card.setObjectName("settingsCard")
        audio_card_layout = QVBoxLayout(audio_card)
        audio_card_layout.setContentsMargins(18, 16, 18, 16)
        audio_card_layout.setSpacing(12)

        audio_header = QLabel("AUDIO SOURCE")
        audio_header.setObjectName("cardHeader")
        audio_header.setFont(self._make_ui_font(11))
        audio_card_layout.addWidget(audio_header)

        self.audio_combo = QComboBox()
        self.audio_combo.addItems(self._audio_sources)
        self._set_combo_value(self.audio_combo, audio_source, default=self._audio_sources[0])
        audio_card_layout.addWidget(self.audio_combo)

        detected_banner = QLabel("\u2713  BlackHole detected")
        detected_banner.setObjectName("detectedBanner")
        detected_banner.setAlignment(Qt.AlignmentFlag.AlignLeft)
        detected_banner.setFont(self._make_ui_font(12))
        audio_card_layout.addWidget(detected_banner)

        root.addWidget(audio_card)

        # ── Voice Playback card ──
        voice_card = QFrame()
        voice_card.setObjectName("settingsCard")
        voice_card_layout = QVBoxLayout(voice_card)
        voice_card_layout.setContentsMargins(18, 16, 18, 16)
        voice_card_layout.setSpacing(8)

        voice_header = QLabel("MEETINGS")
        voice_header.setObjectName("cardHeader")
        voice_header.setFont(self._make_ui_font(11))
        voice_card_layout.addWidget(voice_header)

        beta_note = QLabel("Coming soon")
        beta_note.setObjectName("betaNote")
        beta_note.setFont(self._make_ui_font(13))
        voice_card_layout.addWidget(beta_note)

        root.addWidget(voice_card)

        # ── Bottom buttons ──
        root.addStretch(1)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        bottom.addStretch(1)
        root.addLayout(bottom)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("ghostButton")
        self.cancel_button.clicked.connect(self.reject)
        bottom.addWidget(self.cancel_button)

        self.apply_button = QPushButton("Apply")
        self.apply_button.setObjectName("applyButton")
        self.apply_button.clicked.connect(self.accept)
        bottom.addWidget(self.apply_button)

        # Keep references for compatibility
        self.back_button = self.cancel_button
        self.minimize_button = None
        self.close_button = None

        self.setStyleSheet(
            """
            QDialog {
                background-color: rgba(28, 28, 30, 250);
                border-radius: 14px;
            }
            QLabel {
                color: rgba(255, 255, 255, 200);
                font-size: 13px;
                background: transparent;
            }
            #settingsCard {
                background-color: rgba(255, 255, 255, 8);
                border: none;
                border-radius: 12px;
            }
            #cardHeader {
                color: rgba(255, 255, 255, 90);
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 1.2px;
            }
            #fieldLabel {
                color: rgba(255, 255, 255, 120);
                font-size: 11px;
            }
            #arrowLabel {
                color: rgba(255, 255, 255, 70);
                background: transparent;
            }
            #detectedBanner {
                color: rgba(106, 172, 163, 220);
                background: transparent;
                padding: 2px 0px;
            }
            #betaNote {
                color: rgba(255, 255, 255, 80);
                background: transparent;
                padding: 4px 0px;
            }
            QPushButton {
                background-color: rgba(255, 255, 255, 10);
                color: rgba(255, 255, 255, 200);
                border: none;
                border-radius: 8px;
                padding: 7px 18px;
                min-height: 32px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 18);
            }
            #ghostButton {
                background-color: transparent;
                color: rgba(255, 255, 255, 140);
            }
            #ghostButton:hover {
                background-color: rgba(255, 255, 255, 8);
                color: rgba(255, 255, 255, 200);
            }
            #applyButton {
                background-color: rgba(106, 172, 163, 180);
                color: white;
                font-weight: 600;
                padding: 7px 24px;
            }
            #applyButton:hover {
                background-color: rgba(106, 172, 163, 220);
            }
            QComboBox {
                background-color: rgba(255, 255, 255, 6);
                color: rgba(255, 255, 255, 220);
                border: 1px solid rgba(255, 255, 255, 10);
                border-radius: 8px;
                padding: 8px 12px;
                min-height: 32px;
                font-size: 13px;
            }
            QComboBox:hover {
                background-color: rgba(255, 255, 255, 12);
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                background-color: rgba(44, 44, 46, 250);
                color: rgba(255, 255, 255, 220);
                border: 1px solid rgba(255, 255, 255, 12);
                border-radius: 8px;
                selection-background-color: rgba(106, 172, 163, 60);
                selection-color: white;
                outline: 0;
                padding: 4px;
            }
            """
        )

    def values(self) -> tuple[str, str, str]:
        return (
            self.from_combo.currentText(),
            self.to_combo.currentText(),
            self.audio_combo.currentText(),
        )

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str, default: str) -> None:
        idx = combo.findText(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
            return
        fallback = combo.findText(default)
        combo.setCurrentIndex(fallback if fallback >= 0 else 0)

    @staticmethod
    def _make_ui_font(point_size: int, bold: bool = False) -> QFont:
        font = QFont()
        font.setFamilies([".AppleSystemUIFont", "SF Pro", "Helvetica Neue", "Arial"])
        font.setPointSize(point_size)
        font.setBold(bold)
        return font


class OverlayWindow(QWidget):
    DRAG_ZONE_HEIGHT = 56
    DEFAULT_FULL_TRANSCRIPT_MAX_SEGMENTS = 500
    DEFAULT_HISTORY_VISIBLE_SEGMENTS = 24
    DEFAULT_SUBTITLE_FONT_SIZE = 20
    MONOSPACE_FONT_FAMILIES = ["Menlo", "Consolas", "Courier New", "Monospace"]

    toggle_listening = pyqtSignal(bool)
    copy_requested = pyqtSignal()
    export_requested = pyqtSignal(str)
    clear_requested = pyqtSignal()
    save_session_changed = pyqtSignal(bool)
    debug_toggled = pyqtSignal(bool)
    language_settings_changed = pyqtSignal(str, str)
    audio_source_changed = pyqtSignal(str)
    meeting_mode_changed = pyqtSignal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._drag_offset: Optional[QPoint] = None
        self._listening = False
        self._debug_enabled = False
        self._meeting_mode = False

        self._brand_name = (os.getenv("APP_BRAND_NAME") or "Loro").strip() or "Loro"
        self._source_language = (os.getenv("SOURCE_LANGUAGE") or "Auto-detect").strip() or "Auto-detect"
        self._target_language = (os.getenv("TARGET_LANGUAGE") or "Spanish").strip() or "Spanish"
        self._audio_source = (
            (os.getenv("SYSTEM_AUDIO_DEVICE") or "System loopback (default)").strip()
            or "System loopback (default)"
        )

        max_segments = read_int_env("FULL_TRANSCRIPT_MAX_SEGMENTS", self.DEFAULT_FULL_TRANSCRIPT_MAX_SEGMENTS)
        self.full_transcript_buffer: deque[str] = deque(maxlen=max_segments)
        self._transcript_lock = threading.Lock()
        self._history_visible_segments = read_int_env(
            "HISTORY_VISIBLE_SEGMENTS",
            self.DEFAULT_HISTORY_VISIBLE_SEGMENTS,
        )
        self._history_expanded = False
        self._tools_panel_open = False

        self._subtitle_mode = (os.getenv("SUBTITLE_MODE") or "cinema").strip().lower()
        self._subtitle_max_line_chars = read_int_env("SUBTITLE_MAX_LINE_CHARS", 42)
        self._subtitle_max_lines = read_int_env("SUBTITLE_MAX_LINES", 2)
        self._subtitle_update_ms = read_int_env("SUBTITLE_UPDATE_MS", 300)
        self._subtitle_show_previous = read_bool_env("SUBTITLE_SHOW_PREVIOUS_LINE", True)
        self._overlay_show_timestamps = read_bool_env("OVERLAY_SHOW_TIMESTAMPS", False)
        self._subtitle_preview_reveal_enabled = read_bool_env("SUBTITLE_PREVIEW_REVEAL_ENABLED", True)
        self._subtitle_preview_reveal_interval_ms = read_int_env("SUBTITLE_PREVIEW_REVEAL_INTERVAL_MS", 70)
        self._subtitle_preview_reveal_words_per_tick = read_int_env("SUBTITLE_PREVIEW_REVEAL_WORDS_PER_TICK", 1)

        self._cinema_pending_text: list[str] = []
        self._subtitle_prev_text = ""
        self._subtitle_curr_text = ""
        self._subtitle_preview_text = ""
        self._subtitle_preview_target_words: list[str] = []
        self._subtitle_preview_visible_words = 0
        self._last_subtitle_norm = ""

        self._display_timer = QTimer(self)
        self._display_timer.setSingleShot(True)
        self._display_timer.timeout.connect(self._flush_cinema_text)
        self._preview_reveal_timer = QTimer(self)
        self._preview_reveal_timer.timeout.connect(self._advance_preview_reveal)

        self._build_ui()
        self._apply_window_style()
        self._refresh_state_ui()

    @property
    def save_session_enabled(self) -> bool:
        return self.save_session_checkbox.isChecked()

    def append_segment(self, text: str) -> None:
        cleaned = (text or "").strip()
        if not cleaned:
            return

        with self._transcript_lock:
            self.full_transcript_buffer.append(cleaned)
        display_line = self._display_line(cleaned)
        self._append_to_history_drawer(display_line)
        self._append_to_list_view(display_line)

        if self._subtitle_mode == "cinema" and self._listening:
            display_text = self._strip_timestamp(cleaned)
            if not display_text:
                return
            self._cinema_pending_text.append(display_text)
            if self._subtitle_preview_text:
                self._flush_cinema_text()
                self.clear_live_preview()
            elif not self._display_timer.isActive():
                self._display_timer.start(self._subtitle_update_ms)

    def clear_segments(self) -> None:
        self._cinema_pending_text.clear()
        self._display_timer.stop()
        self._reset_live_subtitles()
        self.transcript_view.clear()
        self.history_view.clear()

    def get_full_transcript_text(self) -> str:
        with self._transcript_lock:
            return "\n".join(self.full_transcript_buffer)

    def set_listening(self, listening: bool) -> None:
        was_listening = self._listening
        self._listening = listening
        if not listening and was_listening:
            self._flush_cinema_text()
        if listening and not was_listening:
            self._reset_live_subtitles()
            # Keep the live experience clean by default on every new run.
            self._history_expanded = False
            self._tools_panel_open = False
        self._refresh_state_ui()

    def set_meeting_summary(self, text: str) -> None:
        self.meeting_summary_label.setText(text)
        self._refresh_state_ui()

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)
        self.status_label.setVisible(self._should_show_status_label(message))

    def show_error_dialog(self, title: str, message: str) -> None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle(title)
        dialog.setText(message)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.exec()

    def set_live_preview(self, text: str) -> None:
        if self._subtitle_mode != "cinema" or not self._listening:
            return
        cleaned = self._strip_timestamp((text or "").strip())
        if not cleaned:
            return
        if self._subtitle_preview_reveal_enabled:
            self._set_live_preview_progressive(cleaned)
            return
        wrapped = self._wrap_subtitle_lines(cleaned)
        norm = self._normalize_for_compare(wrapped)
        if not norm:
            return
        self._subtitle_preview_text = wrapped
        self._paint_live_subtitles()

    def clear_live_preview(self) -> None:
        self._preview_reveal_timer.stop()
        self._subtitle_preview_target_words = []
        self._subtitle_preview_visible_words = 0
        if not self._subtitle_preview_text:
            return
        self._subtitle_preview_text = ""
        self._paint_live_subtitles()

    def _set_live_preview_progressive(self, text: str) -> None:
        words = text.split()
        if not words:
            return
        target_norm = self._normalize_for_compare(" ".join(words))
        current_norm = self._normalize_for_compare(" ".join(self._subtitle_preview_target_words))
        if target_norm == current_norm:
            return

        current_visible_words = (
            self._subtitle_preview_target_words[: self._subtitle_preview_visible_words]
            if self._subtitle_preview_target_words and self._subtitle_preview_visible_words > 0
            else []
        )
        if current_visible_words and words[: len(current_visible_words)] == current_visible_words:
            self._subtitle_preview_visible_words = len(current_visible_words)
        else:
            self._subtitle_preview_visible_words = min(2, len(words))

        self._subtitle_preview_target_words = words
        self._apply_preview_words()
        if self._subtitle_preview_visible_words < len(self._subtitle_preview_target_words):
            self._preview_reveal_timer.start(max(18, self._subtitle_preview_reveal_interval_ms))
        else:
            self._preview_reveal_timer.stop()

    def _advance_preview_reveal(self) -> None:
        if not self._subtitle_preview_target_words:
            self._preview_reveal_timer.stop()
            return
        self._subtitle_preview_visible_words = min(
            len(self._subtitle_preview_target_words),
            self._subtitle_preview_visible_words + max(1, self._subtitle_preview_reveal_words_per_tick),
        )
        self._apply_preview_words()
        if self._subtitle_preview_visible_words >= len(self._subtitle_preview_target_words):
            self._preview_reveal_timer.stop()

    def _apply_preview_words(self) -> None:
        if not self._subtitle_preview_target_words:
            return
        visible = self._subtitle_preview_target_words[: self._subtitle_preview_visible_words]
        if not visible:
            return
        wrapped = self._wrap_subtitle_lines(" ".join(visible))
        norm = self._normalize_for_compare(wrapped)
        if not norm:
            return
        self._subtitle_preview_text = wrapped
        self._paint_live_subtitles()

    def set_debug_mode(self, enabled: bool) -> None:
        self._debug_enabled = enabled
        self.debug_checkbox.blockSignals(True)
        self.debug_checkbox.setChecked(enabled)
        self.debug_checkbox.blockSignals(False)
        self.debug_label.setVisible(enabled and self._tools_panel_open)
        if not enabled:
            self.debug_label.setText("")
            self._history_expanded = False
            self.history_toggle_button.setChecked(False)
        self._refresh_state_ui()

    def set_debug_info(self, text: str, color: str) -> None:
        if not self._debug_enabled:
            return
        self.debug_label.setText(text)
        self.debug_label.setStyleSheet(f"color: {color};")

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        panel = QFrame()
        panel.setObjectName("overlayPanel")
        root.addWidget(panel)
        self._panel = panel

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        layout.addLayout(top_row)

        self.brand_label = QLabel(self._brand_name)
        self.brand_label.setObjectName("brandLabel")
        self.brand_label.setFont(self._make_ui_font(13, bold=True))
        top_row.addWidget(self.brand_label, alignment=Qt.AlignmentFlag.AlignVCenter)

        top_row.addStretch(1)

        # Debug tools toggle — hidden unless debug mode is on
        self.user_button = QPushButton("≡")
        self.user_button.setObjectName("iconButton")
        self.user_button.setCheckable(True)
        self.user_button.setVisible(False)
        self.user_button.clicked.connect(self._toggle_debug_tools)
        top_row.addWidget(self.user_button)

        self.settings_button = QPushButton("⚙")
        self.settings_button.setObjectName("iconButton")
        self.settings_button.clicked.connect(self._open_settings)
        top_row.addWidget(self.settings_button)

        self.minimize_button = QPushButton("–")
        self.minimize_button.setObjectName("iconButton")
        self.minimize_button.clicked.connect(self.showMinimized)
        top_row.addWidget(self.minimize_button)

        self.close_button = QPushButton("×")
        self.close_button.setObjectName("iconButton")
        self.close_button.clicked.connect(self.close)
        top_row.addWidget(self.close_button)

        self.idle_frame = QFrame()
        self.idle_frame.setObjectName("idleFrame")
        idle_layout = QVBoxLayout(self.idle_frame)
        idle_layout.setContentsMargins(0, 4, 0, 4)
        idle_layout.setSpacing(4)

        idle_layout.addStretch(1)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        button_row.addStretch(1)
        self.start_stop_button = QPushButton("START")
        self.start_stop_button.setObjectName("startButton")
        self.start_stop_button.clicked.connect(self._on_start_stop_clicked)
        self.start_stop_button.setMinimumSize(100, 32)
        self.start_stop_button.setIcon(self._make_status_dot_icon("#6aaca3"))
        self.start_stop_button.setIconSize(QSize(8, 8))
        button_row.addWidget(self.start_stop_button)

        self.meeting_mode_button = QPushButton("Meeting")
        self.meeting_mode_button.setObjectName("meetingButton")
        self.meeting_mode_button.setCheckable(True)
        self.meeting_mode_button.toggled.connect(self._on_meeting_mode_toggled)
        button_row.addWidget(self.meeting_mode_button)

        button_row.addStretch(1)
        idle_layout.addLayout(button_row)

        self.meeting_hint_label = QLabel("Transcription only · no translation")
        self.meeting_hint_label.setObjectName("meetingHintLabel")
        self.meeting_hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.meeting_hint_label.setFont(self._make_ui_font(10))
        idle_layout.addWidget(self.meeting_hint_label)

        idle_layout.addStretch(1)
        layout.addWidget(self.idle_frame)

        self.live_frame = QFrame()
        self.live_frame.setObjectName("liveFrame")
        live_layout = QVBoxLayout(self.live_frame)
        live_layout.setContentsMargins(0, 2, 0, 2)
        live_layout.setSpacing(6)

        self.top_rule = QFrame()
        self.top_rule.setObjectName("liveRule")
        self.top_rule.setFixedHeight(1)
        live_layout.addWidget(self.top_rule)

        self.subtitle_box = QFrame()
        self.subtitle_box.setObjectName("subtitleBox")
        subtitle_layout = QVBoxLayout(self.subtitle_box)
        subtitle_layout.setContentsMargins(16, 6, 16, 6)
        subtitle_layout.setSpacing(3)

        self.subtitle_prev_label = QLabel("")
        self.subtitle_prev_label.setObjectName("subtitlePrev")
        self.subtitle_prev_label.setWordWrap(True)
        self.subtitle_prev_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        subtitle_layout.addWidget(self.subtitle_prev_label)

        self.subtitle_curr_label = QLabel("")
        self.subtitle_curr_label.setObjectName("subtitleCurr")
        self.subtitle_curr_label.setWordWrap(True)
        self.subtitle_curr_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        subtitle_layout.addWidget(self.subtitle_curr_label)
        self.subtitle_box.setMinimumHeight(80)
        live_layout.addWidget(self.subtitle_box)

        self.bottom_rule = QFrame()
        self.bottom_rule.setObjectName("liveRule")
        self.bottom_rule.setFixedHeight(1)
        live_layout.addWidget(self.bottom_rule)

        self.transcript_view = QTextEdit()
        self.transcript_view.setObjectName("liveTranscript")
        self.transcript_view.setReadOnly(True)
        self.transcript_view.setAcceptRichText(False)
        self.transcript_view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.transcript_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.transcript_view.setFont(self._make_monospace_font(read_int_env("OVERLAY_FONT_SIZE", 18)))
        self.transcript_view.setMinimumHeight(96)
        live_layout.addWidget(self.transcript_view)

        self.meeting_summary_label = QLabel("")
        self.meeting_summary_label.setObjectName("meetingSummaryLabel")
        self.meeting_summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.meeting_summary_label.setFont(self._make_ui_font(12))
        self.meeting_summary_label.setWordWrap(True)
        live_layout.addWidget(self.meeting_summary_label)

        layout.addWidget(self.live_frame)

        self.history_frame = QFrame()
        self.history_frame.setObjectName("historyFrame")
        history_layout = QVBoxLayout(self.history_frame)
        history_layout.setContentsMargins(12, 10, 12, 10)
        history_layout.setSpacing(6)

        history_title = QLabel("history")
        history_title.setObjectName("historyTitle")
        history_title.setFont(self._make_monospace_font(11, bold=True))
        history_layout.addWidget(history_title)

        self.history_view = QTextEdit()
        self.history_view.setObjectName("historyView")
        self.history_view.setReadOnly(True)
        self.history_view.setAcceptRichText(False)
        self.history_view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.history_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.history_view.setFont(self._make_monospace_font(12))
        history_layout.addWidget(self.history_view)

        layout.addWidget(self.history_frame)

        self.footer_frame = QFrame()
        self.footer_frame.setObjectName("footerFrame")
        layout.addWidget(self.footer_frame)

        footer_row = QHBoxLayout(self.footer_frame)
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.setSpacing(10)

        live_badge = QHBoxLayout()
        live_badge.setSpacing(6)
        self.live_dot = QFrame()
        self.live_dot.setObjectName("liveDot")
        self.live_dot.setFixedSize(12, 12)
        live_badge.addWidget(self.live_dot)

        self.live_label = QLabel("LIVE")
        self.live_label.setObjectName("liveLabel")
        self.live_label.setFont(self._make_ui_font(11, bold=True))
        live_badge.addWidget(self.live_label)

        footer_row.addLayout(live_badge)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setFont(self._make_ui_font(12))
        self.status_label.setMaximumWidth(500)
        footer_row.addWidget(self.status_label, stretch=1)

        self.meeting_export_button = QPushButton("Export")
        self.meeting_export_button.setObjectName("meetingExportButton")
        self.meeting_export_button.clicked.connect(self._on_export_clicked)
        footer_row.addWidget(self.meeting_export_button, alignment=Qt.AlignmentFlag.AlignRight)

        self.stop_button = QPushButton("STOP")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.clicked.connect(self._on_start_stop_clicked)
        self.stop_button.setMinimumSize(88, 30)
        self.stop_button.setIcon(self._make_status_dot_icon("#ff6478"))
        self.stop_button.setIconSize(QSize(8, 8))
        footer_row.addWidget(self.stop_button, alignment=Qt.AlignmentFlag.AlignRight)

        self.tools_frame = QFrame()
        self.tools_frame.setObjectName("toolsFrame")
        layout.addWidget(self.tools_frame)

        self.debug_bar = QHBoxLayout(self.tools_frame)
        self.debug_bar.setContentsMargins(12, 10, 12, 10)
        self.debug_bar.setSpacing(8)

        self.copy_button = QPushButton("Copy")
        self.copy_button.clicked.connect(self.copy_requested.emit)
        self.debug_bar.addWidget(self.copy_button)

        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_requested.emit)
        self.debug_bar.addWidget(self.clear_button)

        self.history_toggle_button = QPushButton("History")
        self.history_toggle_button.setCheckable(True)
        self.history_toggle_button.toggled.connect(self._on_history_toggled)
        self.debug_bar.addWidget(self.history_toggle_button)

        self.export_button = QPushButton("Export")
        self.export_button.clicked.connect(self._on_export_clicked)
        self.debug_bar.addWidget(self.export_button)

        self.save_session_checkbox = QCheckBox("Save Session")
        self.save_session_checkbox.stateChanged.connect(
            lambda state: self.save_session_changed.emit(state == Qt.CheckState.Checked.value)
        )
        self.debug_bar.addWidget(self.save_session_checkbox)

        self.debug_checkbox = QCheckBox("Debug")
        self.debug_checkbox.stateChanged.connect(
            lambda state: self.debug_toggled.emit(state == Qt.CheckState.Checked.value)
        )
        self.debug_bar.addWidget(self.debug_checkbox)

        self.debug_label = QLabel("")
        self.debug_label.setObjectName("debugLabel")
        self.debug_label.setVisible(False)
        self.debug_label.setFont(self._make_monospace_font(11))
        self.debug_bar.addWidget(self.debug_label)

        self.debug_bar.addStretch(1)

        self.shortcut_label = QLabel("Space start/stop  ·  S settings  ·  D debug  ·  H history")
        self.shortcut_label.setObjectName("shortcutHint")
        self.shortcut_label.setFont(self._make_monospace_font(10))
        self.debug_bar.addWidget(self.shortcut_label)

        self.tools_minimize_button = QPushButton("Min")
        self.tools_minimize_button.clicked.connect(self.showMinimized)
        self.debug_bar.addWidget(self.tools_minimize_button)

        subtitle_curr_font = self._make_monospace_font(
            read_int_env("SUBTITLE_FONT_SIZE", self.DEFAULT_SUBTITLE_FONT_SIZE),
            bold=True,
        )
        subtitle_curr_size = max(15, min(subtitle_curr_font.pointSize(), 19))
        self.subtitle_curr_label.setFont(self._make_ui_font(subtitle_curr_size))
        self.subtitle_prev_label.setFont(self._make_ui_font(max(11, subtitle_curr_size - 6)))
        self._disable_focus_rings()

        self._install_shortcuts()

    def showEvent(self, event: object) -> None:
        super().showEvent(event)  # type: ignore[misc]
        if not getattr(self, "_vibrancy_applied", False):
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(80, self._apply_native_vibrancy)

    def _apply_native_vibrancy(self) -> None:
        if getattr(self, "_vibrancy_applied", False):
            return
        try:
            from native_vibrancy import apply_vibrancy
            success = apply_vibrancy(self, corner_radius=16.0, material="hud")
            self._vibrancy_applied = success
            if success:
                self._apply_vibrancy_stylesheet()
        except Exception:
            self._vibrancy_applied = False

    def _apply_vibrancy_stylesheet(self) -> None:
        """Reduce panel opacity so NSVisualEffectView blur shows through."""
        self._panel.setStyleSheet(
            """
            #overlayPanel {
                background-color: rgba(10, 12, 18, 70);
                border: 1px solid rgba(255, 255, 255, 28);
                border-radius: 16px;
            }
            """
        )

    def _apply_window_style(self) -> None:
        self.setWindowTitle(f"{self._brand_name} - Universal Real-Time Audio Translator")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowFlag(Qt.WindowType.Tool, False)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(520, 110)
        self.resize(620, 118)

        self.setStyleSheet(
            """
            /* ── Panel ── */
            #overlayPanel {
                background-color: rgba(14, 18, 26, 145);
                border: 1px solid rgba(255, 255, 255, 22);
                border-radius: 16px;
            }

            /* ── Header ── */
            #brandLabel {
                color: white;
                letter-spacing: 1.8px;
                padding-left: 4px;
            }
            #iconButton {
                min-width: 26px;
                min-height: 24px;
                max-height: 24px;
                border-radius: 8px;
                background-color: transparent;
                color: rgba(255, 255, 255, 180);
                border: none;
                padding: 0px 5px;
                font-size: 13px;
            }
            #iconButton:hover {
                background-color: rgba(255, 255, 255, 18);
                color: white;
            }
            #iconButton:checked {
                background-color: rgba(255, 255, 255, 25);
                color: white;
            }

            /* ── Meeting toggle ── */
            #meetingButton {
                min-height: 24px;
                max-height: 24px;
                border-radius: 12px;
                background-color: rgba(255, 255, 255, 14);
                color: rgba(255, 255, 255, 190);
                border: none;
                padding: 0px 12px;
                font-size: 11px;
                font-weight: 500;
                letter-spacing: 0.6px;
            }
            #meetingButton:hover {
                background-color: rgba(255, 255, 255, 24);
                color: white;
            }
            #meetingButton:checked {
                background-color: rgba(106, 172, 163, 60);
                color: rgba(106, 172, 163, 240);
                border: none;
            }

            /* ── Idle state ── */
            #idleFrame {
                background-color: transparent;
            }
            #startButton {
                background-color: rgba(255, 255, 255, 16);
                color: white;
                border: none;
                border-radius: 20px;
                font-size: 13px;
                font-weight: 600;
                letter-spacing: 2.0px;
                padding: 6px 20px;
            }
            #startButton:hover {
                background-color: rgba(255, 255, 255, 28);
            }

            /* ── Live frame ── */
            #liveRule {
                background-color: rgba(255, 255, 255, 12);
                border: none;
            }
            #liveFrame {
                background-color: transparent;
            }

            /* ── Subtitles (cinema mode) ── */
            #subtitleBox {
                background-color: transparent;
                border: none;
                border-radius: 0px;
            }
            #subtitlePrev {
                color: rgba(255, 255, 255, 170);
                font-weight: 420;
            }
            #subtitleCurr {
                color: white;
                font-weight: 600;
            }
            #subtitleCurr[preview="true"] {
                color: rgba(255, 255, 255, 180);
                font-weight: 460;
            }

            /* ── Transcript (list / meeting mode) ── */
            #liveTranscript {
                background-color: rgba(0, 0, 0, 20);
                color: rgba(255, 255, 255, 235);
                border: 1px solid rgba(255, 255, 255, 12);
                border-radius: 14px;
                padding: 10px;
            }

            /* ── History drawer ── */
            #historyFrame {
                background-color: rgba(0, 0, 0, 40);
                border: 1px solid rgba(255, 255, 255, 10);
                border-radius: 16px;
            }
            #historyTitle {
                color: rgba(255, 255, 255, 140);
            }
            #historyView {
                background-color: transparent;
                color: rgba(255, 255, 255, 160);
                border: none;
            }

            /* ── Debug tools ── */
            #toolsFrame {
                background-color: rgba(0, 0, 0, 50);
                border: 1px solid rgba(255, 255, 255, 12);
                border-radius: 16px;
            }

            /* ── Footer ── */
            #liveDot {
                background-color: rgba(106, 172, 163, 255);
                border-radius: 6px;
            }
            #liveLabel {
                color: rgba(106, 172, 163, 220);
                letter-spacing: 2.6px;
            }
            #statusLabel {
                color: rgba(255, 255, 255, 100);
                font-size: 11px;
            }
            #footerFrame {
                background-color: transparent;
            }

            /* ── Meeting mode labels ── */
            #meetingHintLabel {
                color: rgba(106, 172, 163, 180);
                font-size: 11px;
                padding: 4px 0px 2px 0px;
            }
            #meetingSummaryLabel {
                color: rgba(255, 255, 255, 160);
                font-size: 12px;
                padding: 8px 16px;
                background-color: rgba(0, 0, 0, 30);
                border-radius: 10px;
                margin: 4px 0px;
            }

            /* ── Export button (teal accent) ── */
            #meetingExportButton {
                background-color: rgba(106, 172, 163, 30);
                color: rgba(106, 172, 163, 230);
                border: 1px solid rgba(106, 172, 163, 60);
                border-radius: 12px;
                font-size: 12px;
                padding: 4px 14px;
                min-height: 34px;
            }
            #meetingExportButton:hover {
                background-color: rgba(106, 172, 163, 50);
            }

            /* ── Stop button ── */
            #stopButton {
                background-color: rgba(255, 255, 255, 10);
                color: rgba(255, 100, 120, 220);
                border: none;
                border-radius: 16px;
                font-size: 12px;
                font-weight: 500;
                letter-spacing: 1.3px;
                padding: 4px 14px;
            }
            #stopButton:hover {
                background-color: rgba(255, 100, 120, 25);
            }

            /* ── Debug ── */
            #debugLabel {
                color: rgba(106, 172, 163, 200);
                font-size: 12px;
            }
            #shortcutHint {
                color: rgba(255, 255, 255, 90);
            }

            /* ── Base defaults ── */
            QLabel, QCheckBox {
                color: rgba(255, 255, 255, 200);
            }
            QPushButton {
                background-color: rgba(255, 255, 255, 10);
                color: rgba(255, 255, 255, 210);
                border: 1px solid rgba(255, 255, 255, 14);
                border-radius: 10px;
                padding: 3px 10px;
                min-height: 28px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 20);
            }
            QPushButton:focus {
                outline: none;
            }
            """
        )

    def _disable_focus_rings(self) -> None:
        for button in self.findChildren(QPushButton):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)

    def _install_shortcuts(self) -> None:
        self._shortcut_start_stop = QShortcut(QKeySequence("Space"), self)
        self._shortcut_start_stop.activated.connect(self._on_start_stop_clicked)

        self._shortcut_debug = QShortcut(QKeySequence("D"), self)
        self._shortcut_debug.activated.connect(lambda: self.debug_checkbox.toggle())

        self._shortcut_settings = QShortcut(QKeySequence("S"), self)
        self._shortcut_settings.activated.connect(self._open_settings)

        self._shortcut_history = QShortcut(QKeySequence("H"), self)
        self._shortcut_history.activated.connect(lambda: self.history_toggle_button.toggle())

        self._shortcut_clear = QShortcut(QKeySequence("C"), self)
        self._shortcut_clear.activated.connect(self.clear_requested.emit)

        self._shortcut_export = QShortcut(QKeySequence("E"), self)
        self._shortcut_export.activated.connect(self._on_export_clicked)

        self._shortcut_copy = QShortcut(QKeySequence("Ctrl+C"), self)
        self._shortcut_copy.activated.connect(self.copy_requested.emit)

    def _refresh_state_ui(self) -> None:
        self.idle_frame.setVisible(not self._listening)
        self.live_frame.setVisible(self._listening)

        has_meeting_content = self._meeting_mode and bool(self.full_transcript_buffer)
        self.subtitle_box.setVisible(self._listening and not self._meeting_mode)
        show_transcript = (
            (self._listening and self._meeting_mode)
            or has_meeting_content
            or (self._listening and self._tools_panel_open and self._subtitle_mode == "list")
        )
        self.transcript_view.setVisible(show_transcript)

        self.live_dot.setVisible(self._listening)
        self.live_label.setVisible(self._listening)
        self.meeting_export_button.setVisible(has_meeting_content)
        self.stop_button.setVisible(self._listening)
        self.footer_frame.setVisible(self._listening or has_meeting_content)

        self.status_label.setVisible(self._should_show_status_label(self.status_label.text()))
        self.history_frame.setVisible(self._listening and self._tools_panel_open and self._history_expanded)
        show_advanced_tools = self._listening and self._tools_panel_open and self._debug_enabled
        self.tools_frame.setVisible(show_advanced_tools)
        self.debug_label.setVisible(show_advanced_tools and self._debug_enabled)

        self.start_stop_button.setText("RECORD" if self._meeting_mode else "START")
        self.user_button.setVisible(self._debug_enabled)
        self.user_button.setChecked(self._tools_panel_open and self._debug_enabled)

        self.meeting_hint_label.setVisible(self._meeting_mode and not self._listening)
        self.meeting_summary_label.setVisible(has_meeting_content and not self._listening)

        if self._meeting_mode:
            self.transcript_view.setFont(self._make_ui_font(14))
            self.transcript_view.setMinimumHeight(240)
        else:
            self.transcript_view.setFont(self._make_monospace_font(read_int_env("OVERLAY_FONT_SIZE", 18)))
            self.transcript_view.setMinimumHeight(96)

        if self._listening and self._meeting_mode:
            self.live_label.setText("REC")
            self.live_dot.setStyleSheet("background-color: rgba(240, 160, 50, 255); border-radius: 6px;")
            self.live_label.setStyleSheet("color: rgba(240, 160, 50, 200); letter-spacing: 2.6px;")
        else:
            self.live_label.setText("LIVE")
            self.live_dot.setStyleSheet("")
            self.live_label.setStyleSheet("")

        if self._listening and self._meeting_mode:
            self.setMinimumHeight(320)
            if self.height() < 320:
                self.resize(max(self.width(), 620), 340)
        elif self._listening:
            self.setMinimumHeight(180)
            if self.height() < 180:
                self.resize(max(self.width(), 620), 190)
        elif has_meeting_content:
            self.setMinimumHeight(250)
            if self.height() < 250:
                self.resize(max(self.width(), 620), 270)
        else:
            target_idle_height = 118 if not self._meeting_mode else 140
            self.setMinimumHeight(target_idle_height)
            if self.height() != target_idle_height:
                self.resize(max(self.width(), 620), target_idle_height)

    def _on_start_stop_clicked(self) -> None:
        next_state = not self._listening
        self.set_listening(next_state)
        self.toggle_listening.emit(next_state)

    def _on_meeting_mode_toggled(self, checked: bool) -> None:
        self._meeting_mode = checked
        self._refresh_state_ui()
        self.meeting_mode_changed.emit(checked)

    def _on_history_toggled(self, checked: bool) -> None:
        self._history_expanded = checked
        self._refresh_state_ui()

    def _toggle_debug_tools(self) -> None:
        if not self._debug_enabled:
            self._tools_panel_open = False
            self._refresh_state_ui()
            return
        self._tools_panel_open = not self._tools_panel_open
        self._refresh_state_ui()

    def _show_info_hint(self) -> None:
        self.set_status(
            f"{self._brand_name}: {self._source_language} -> {self._target_language} | {self._audio_source}"
        )
        self.status_label.setVisible(True)

    def _open_settings(self) -> None:
        dialog = SettingsDialog(
            brand_name=self._brand_name,
            source_language=self._source_language,
            target_language=self._target_language,
            audio_source=self._audio_source,
            audio_sources=self._list_audio_sources(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        source_lang, target_lang, audio_source = dialog.values()
        language_changed = (source_lang, target_lang) != (self._source_language, self._target_language)
        audio_changed = audio_source != self._audio_source

        self._source_language = source_lang
        self._target_language = target_lang
        self._audio_source = audio_source

        if language_changed:
            self.language_settings_changed.emit(source_lang, target_lang)
        if audio_changed:
            self.audio_source_changed.emit(audio_source)

        self.set_status(f"Settings updated: {source_lang} -> {target_lang}")
        self.status_label.setVisible(True)

    @staticmethod
    def _list_audio_sources() -> list[str]:
        try:
            names = SystemAudioListener.list_input_devices()
        except Exception:
            names = []
        if not names:
            return ["System loopback (default)"]
        return names

    def _on_export_clicked(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Transcript",
            "translated_transcript.txt",
            "Text files (*.txt)",
        )
        if path:
            self.export_requested.emit(path)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override naming
        if event.button() == Qt.MouseButton.LeftButton:
            local_pos = event.position().toPoint()
            if local_pos.y() <= self.DRAG_ZONE_HEIGHT:
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override naming
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override naming
        self._drag_offset = None
        event.accept()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override naming
        super().resizeEvent(event)

    def _is_user_at_bottom(self) -> bool:
        scrollbar = self.transcript_view.verticalScrollBar()
        return scrollbar.value() >= (scrollbar.maximum() - 2)

    def _append_to_list_view(self, line: str) -> None:
        should_scroll = self._is_user_at_bottom()
        if self.transcript_view.toPlainText():
            self.transcript_view.insertPlainText("\n")
        self.transcript_view.insertPlainText(line)
        if should_scroll:
            cursor = self.transcript_view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.transcript_view.setTextCursor(cursor)
            self.transcript_view.ensureCursorVisible()

    def _append_to_history_drawer(self, line: str) -> None:
        if not line:
            return
        with self._transcript_lock:
            rendered_history = [self._display_line(entry) for entry in self.full_transcript_buffer]
        tail = rendered_history[-self._history_visible_segments :]
        self.history_view.setPlainText("\n".join(tail))
        cursor = self.history_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.history_view.setTextCursor(cursor)
        self.history_view.ensureCursorVisible()

    def _flush_cinema_text(self) -> None:
        if not self._cinema_pending_text:
            return
        merged = " ".join(part for part in self._cinema_pending_text if part).strip()
        self._cinema_pending_text.clear()
        if not merged:
            return

        rendered = self._wrap_subtitle_lines(merged)
        norm = self._normalize_for_compare(rendered)
        if not norm or norm == self._last_subtitle_norm:
            return

        if self._subtitle_show_previous and self._subtitle_curr_text:
            self._subtitle_prev_text = self._subtitle_curr_text
        elif not self._subtitle_show_previous:
            self._subtitle_prev_text = ""
        self._subtitle_curr_text = rendered
        self._last_subtitle_norm = norm
        self._paint_live_subtitles()

    def _render_full_history(self) -> None:
        with self._transcript_lock:
            visible_history = [self._display_line(line) for line in self.full_transcript_buffer]
        tail = visible_history[-self._history_visible_segments :]
        self.transcript_view.setPlainText("\n".join(tail))
        self.history_view.setPlainText("\n".join(tail))

    def _wrap_subtitle_lines(self, text: str) -> str:
        words = text.split()
        if not words:
            return ""
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) <= self._subtitle_max_line_chars or not current:
                current = candidate
                continue
            lines.append(current)
            current = word
        if current:
            lines.append(current)
        visible = lines[-self._subtitle_max_lines :]
        return "\n".join(visible)

    @staticmethod
    def _strip_timestamp(text: str) -> str:
        return text.split("] ", 1)[1].strip() if text.startswith("[") and "] " in text else text

    def _display_line(self, text: str) -> str:
        return text if self._overlay_show_timestamps else self._strip_timestamp(text)

    def _paint_live_subtitles(self) -> None:
        preview_active = bool(self._subtitle_preview_text.strip())
        prev_visible = self._subtitle_show_previous and bool(self._subtitle_prev_text.strip())
        prev_text = self._subtitle_prev_text if prev_visible else ""
        curr_text = self._subtitle_curr_text
        curr_preview = False

        if preview_active:
            curr_text = self._subtitle_preview_text
            curr_preview = True
            if self._subtitle_show_previous and self._subtitle_curr_text.strip():
                prev_visible = True
                prev_text = self._subtitle_curr_text

        self.subtitle_prev_label.setVisible(prev_visible)
        self.subtitle_prev_label.setText(prev_text if prev_visible else "")
        self.subtitle_curr_label.setText(curr_text)
        self.subtitle_curr_label.setProperty("preview", curr_preview)
        self.subtitle_curr_label.style().unpolish(self.subtitle_curr_label)
        self.subtitle_curr_label.style().polish(self.subtitle_curr_label)

    def _reset_live_subtitles(self) -> None:
        self._preview_reveal_timer.stop()
        self._subtitle_prev_text = ""
        self._subtitle_curr_text = ""
        self._subtitle_preview_text = ""
        self._subtitle_preview_target_words = []
        self._subtitle_preview_visible_words = 0
        self._last_subtitle_norm = ""
        self.subtitle_prev_label.clear()
        self.subtitle_curr_label.clear()
        self.subtitle_prev_label.setVisible(False)
        self.subtitle_curr_label.setProperty("preview", False)
        self.subtitle_curr_label.style().unpolish(self.subtitle_curr_label)
        self.subtitle_curr_label.style().polish(self.subtitle_curr_label)

    @staticmethod
    def _normalize_for_compare(text: str) -> str:
        normalized = text.lower().strip()
        normalized = " ".join(normalized.split())
        return normalized

    def _should_show_status_label(self, text: str) -> bool:
        if not self._listening:
            return False
        normalized = (text or "").lower()
        return (self._debug_enabled and self._tools_panel_open) or "error" in normalized

    @staticmethod
    def _make_status_dot_icon(hex_color: str) -> QIcon:
        pixmap = QPixmap(12, 12)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(hex_color))
        painter.drawEllipse(1, 1, 10, 10)
        painter.end()
        return QIcon(pixmap)

    @staticmethod
    def _make_ui_font(point_size: int, bold: bool = False) -> QFont:
        font = QFont()
        # .AppleSystemUIFont resolves to SF Pro on macOS
        font.setFamilies([".AppleSystemUIFont", "SF Pro", "Helvetica Neue", "Arial"])
        font.setPointSize(point_size)
        font.setBold(bold)
        return font

    @classmethod
    def _make_monospace_font(cls, point_size: int, bold: bool = False) -> QFont:
        font = QFont()
        font.setFamilies(cls.MONOSPACE_FONT_FAMILIES)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(point_size)
        font.setBold(bold)
        return font
