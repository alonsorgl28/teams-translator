from __future__ import annotations

import os
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
    QPushButton,
    QSizeGrip,
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
        self.setMinimumWidth(860)

        root = QVBoxLayout(self)
        root.setContentsMargins(30, 24, 30, 28)
        root.setSpacing(16)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        root.addLayout(top_row)

        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.reject)
        top_row.addWidget(self.back_button, alignment=Qt.AlignmentFlag.AlignLeft)

        top_row.addStretch(1)

        brand = QLabel(self._brand_name)
        brand.setObjectName("settingsBrand")
        brand.setFont(self._make_ui_font(18, bold=True))
        top_row.addWidget(brand, alignment=Qt.AlignmentFlag.AlignCenter)

        top_row.addStretch(1)

        self.minimize_button = QPushButton("-")
        self.minimize_button.clicked.connect(self.showMinimized)
        top_row.addWidget(self.minimize_button)

        self.close_button = QPushButton("X")
        self.close_button.clicked.connect(self.reject)
        top_row.addWidget(self.close_button)

        section_title = QLabel("Languages")
        section_title.setObjectName("sectionTitle")
        section_title.setFont(self._make_ui_font(14, bold=True))
        root.addWidget(section_title)

        lang_row = QHBoxLayout()
        lang_row.setSpacing(18)
        root.addLayout(lang_row)

        left_lang = QVBoxLayout()
        left_lang.setSpacing(6)
        lang_row.addLayout(left_lang)

        from_label = QLabel("From")
        from_label.setObjectName("fieldLabel")
        left_lang.addWidget(from_label)
        self.from_combo = QComboBox()
        self.from_combo.addItems(self.DEFAULT_LANG_OPTIONS)
        self._set_combo_value(self.from_combo, source_language, default="Auto-detect")
        left_lang.addWidget(self.from_combo)

        mid_arrow = QLabel("->")
        mid_arrow.setObjectName("arrowLabel")
        mid_arrow.setFont(self._make_ui_font(20, bold=True))
        mid_arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lang_row.addWidget(mid_arrow, alignment=Qt.AlignmentFlag.AlignCenter)

        right_lang = QVBoxLayout()
        right_lang.setSpacing(6)
        lang_row.addLayout(right_lang)

        to_label = QLabel("To")
        to_label.setObjectName("fieldLabel")
        right_lang.addWidget(to_label)
        self.to_combo = QComboBox()
        self.to_combo.addItems(self.DEFAULT_TARGET_OPTIONS)
        self._set_combo_value(self.to_combo, target_language, default="Spanish")
        right_lang.addWidget(self.to_combo)

        audio_title = QLabel("Audio Source")
        audio_title.setObjectName("sectionTitle")
        audio_title.setFont(self._make_ui_font(14, bold=True))
        root.addWidget(audio_title)

        self.audio_combo = QComboBox()
        self.audio_combo.addItems(self._audio_sources)
        self._set_combo_value(self.audio_combo, audio_source, default=self._audio_sources[0])
        root.addWidget(self.audio_combo)

        detected_banner = QLabel("BlackHole detected - select it above for echo-free voice")
        detected_banner.setObjectName("detectedBanner")
        detected_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detected_banner.setWordWrap(True)
        root.addWidget(detected_banner)

        voice_title = QLabel("Voice Playback")
        voice_title.setObjectName("sectionTitle")
        voice_title.setFont(self._make_ui_font(14, bold=True))
        root.addWidget(voice_title)

        beta_note = QLabel("Voice mode is in private beta\nRequest Access soon")
        beta_note.setObjectName("betaNote")
        beta_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        beta_note.setWordWrap(True)
        root.addWidget(beta_note)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        root.addLayout(bottom)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        bottom.addWidget(self.cancel_button)

        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self.accept)
        bottom.addWidget(self.apply_button)

        self.setStyleSheet(
            """
            QDialog {
                background-color: #f2f0eb;
                border: 1px solid rgba(159, 171, 179, 96);
                border-radius: 24px;
            }
            QLabel {
                color: #42505b;
                font-size: 13px;
            }
            #settingsBrand {
                color: #4ea894;
                letter-spacing: 0.4px;
            }
            #sectionTitle {
                color: #2e3a43;
                font-size: 17px;
            }
            #fieldLabel {
                color: #66747f;
            }
            #arrowLabel {
                color: #9aa6ad;
                min-width: 36px;
            }
            #detectedBanner {
                background-color: #dfeeee;
                color: #4b9a8a;
                border-radius: 16px;
                padding: 12px;
                border: 1px solid rgba(99, 173, 155, 56);
            }
            #betaNote {
                background-color: #e8dfcd;
                color: #5f6974;
                border-radius: 18px;
                border: 1px dashed rgba(175, 163, 133, 120);
                padding: 20px;
            }
            QPushButton {
                background-color: rgba(255, 255, 255, 198);
                color: #5f6d77;
                border: 1px solid rgba(181, 190, 197, 242);
                border-radius: 16px;
                padding: 7px 16px;
                min-height: 38px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 245);
            }
            QComboBox {
                background-color: rgba(255, 255, 255, 245);
                color: #344049;
                border: 1px solid rgba(207, 212, 217, 242);
                border-radius: 20px;
                padding: 9px 14px;
                min-height: 38px;
                font-size: 15px;
            }
            QComboBox::drop-down {
                border: none;
                width: 28px;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #344049;
                border: 1px solid rgba(193, 198, 205, 235);
                selection-background-color: rgba(98, 163, 146, 32);
                selection-color: #1e272e;
                outline: 0;
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
        font.setFamilies(["Avenir Next", "Helvetica Neue", "Inter", "Arial", "Sans"])
        font.setPointSize(point_size)
        font.setBold(bold)
        return font


class OverlayWindow(QWidget):
    DRAG_ZONE_HEIGHT = 56
    DEFAULT_FULL_TRANSCRIPT_MAX_SEGMENTS = 500
    DEFAULT_HISTORY_VISIBLE_SEGMENTS = 24
    DEFAULT_SUBTITLE_FONT_SIZE = 28
    MONOSPACE_FONT_FAMILIES = ["Menlo", "Consolas", "Courier New", "Monospace"]

    toggle_listening = pyqtSignal(bool)
    copy_requested = pyqtSignal()
    export_requested = pyqtSignal(str)
    clear_requested = pyqtSignal()
    save_session_changed = pyqtSignal(bool)
    debug_toggled = pyqtSignal(bool)
    language_settings_changed = pyqtSignal(str, str)
    audio_source_changed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._drag_offset: Optional[QPoint] = None
        self._listening = False
        self._debug_enabled = False

        self._brand_name = (os.getenv("APP_BRAND_NAME") or "Loro").strip() or "Loro"
        self._source_language = (os.getenv("SOURCE_LANGUAGE") or "Auto-detect").strip() or "Auto-detect"
        self._target_language = (os.getenv("TARGET_LANGUAGE") or "Spanish").strip() or "Spanish"
        self._audio_source = (
            (os.getenv("SYSTEM_AUDIO_DEVICE") or "System loopback (default)").strip()
            or "System loopback (default)"
        )

        max_segments = read_int_env("FULL_TRANSCRIPT_MAX_SEGMENTS", self.DEFAULT_FULL_TRANSCRIPT_MAX_SEGMENTS)
        self.full_transcript_buffer: deque[str] = deque(maxlen=max_segments)
        self._history_visible_segments = read_int_env(
            "HISTORY_VISIBLE_SEGMENTS",
            self.DEFAULT_HISTORY_VISIBLE_SEGMENTS,
        )
        self._history_expanded = read_bool_env("HISTORY_PANEL_OPEN", False)
        self._tools_panel_open = read_bool_env("UI_TOOLS_PANEL_OPEN", False)

        self._subtitle_mode = (os.getenv("SUBTITLE_MODE") or "cinema").strip().lower()
        self._subtitle_max_line_chars = read_int_env("SUBTITLE_MAX_LINE_CHARS", 42)
        self._subtitle_max_lines = read_int_env("SUBTITLE_MAX_LINES", 2)
        self._subtitle_update_ms = read_int_env("SUBTITLE_UPDATE_MS", 300)
        self._subtitle_show_previous = read_bool_env("SUBTITLE_SHOW_PREVIOUS_LINE", True)
        self._overlay_show_timestamps = read_bool_env("OVERLAY_SHOW_TIMESTAMPS", False)

        self._cinema_pending_text: list[str] = []
        self._subtitle_prev_text = ""
        self._subtitle_curr_text = ""
        self._subtitle_preview_text = ""
        self._last_subtitle_norm = ""

        self._display_timer = QTimer(self)
        self._display_timer.setSingleShot(True)
        self._display_timer.timeout.connect(self._flush_cinema_text)

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
        return "\n".join(self.full_transcript_buffer)

    def set_listening(self, listening: bool) -> None:
        was_listening = self._listening
        self._listening = listening
        if not listening and was_listening:
            self._flush_cinema_text()
        if listening and not was_listening:
            self._reset_live_subtitles()
        self._refresh_state_ui()

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)
        self.status_label.setVisible(self._should_show_status_label(message))

    def set_live_preview(self, text: str) -> None:
        if self._subtitle_mode != "cinema" or not self._listening:
            return
        cleaned = self._strip_timestamp((text or "").strip())
        if not cleaned:
            return
        wrapped = self._wrap_subtitle_lines(cleaned)
        norm = self._normalize_for_compare(wrapped)
        if not norm:
            return
        self._subtitle_preview_text = wrapped
        self._paint_live_subtitles()

    def clear_live_preview(self) -> None:
        if not self._subtitle_preview_text:
            return
        self._subtitle_preview_text = ""
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
        layout.setContentsMargins(26, 18, 26, 18)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        layout.addLayout(top_row)

        self.brand_label = QLabel(self._brand_name)
        self.brand_label.setObjectName("brandLabel")
        self.brand_label.setFont(self._make_ui_font(15, bold=True))
        top_row.addWidget(self.brand_label, alignment=Qt.AlignmentFlag.AlignVCenter)

        top_row.addStretch(1)

        self.user_button = QPushButton("≡")
        self.user_button.setObjectName("iconButton")
        self.user_button.setCheckable(True)
        self.user_button.clicked.connect(self._toggle_debug_tools)
        top_row.addWidget(self.user_button)

        self.settings_button = QPushButton("⚙")
        self.settings_button.setObjectName("iconButton")
        self.settings_button.clicked.connect(self._open_settings)
        top_row.addWidget(self.settings_button)

        self.info_button = QPushButton("i")
        self.info_button.setObjectName("iconButton")
        self.info_button.clicked.connect(self._show_info_hint)
        top_row.addWidget(self.info_button)

        self.close_button = QPushButton("×")
        self.close_button.setObjectName("iconButton")
        self.close_button.clicked.connect(self.close)
        top_row.addWidget(self.close_button)

        self.idle_frame = QFrame()
        self.idle_frame.setObjectName("idleFrame")
        idle_layout = QVBoxLayout(self.idle_frame)
        idle_layout.setContentsMargins(0, 18, 0, 26)
        idle_layout.setSpacing(10)

        idle_layout.addStretch(1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.start_stop_button = QPushButton("START")
        self.start_stop_button.setObjectName("startButton")
        self.start_stop_button.clicked.connect(self._on_start_stop_clicked)
        self.start_stop_button.setMinimumSize(148, 50)
        self.start_stop_button.setIcon(self._make_status_dot_icon("#2dd86f"))
        self.start_stop_button.setIconSize(QSize(10, 10))
        button_row.addWidget(self.start_stop_button)
        button_row.addStretch(1)
        idle_layout.addLayout(button_row)

        idle_layout.addStretch(1)
        layout.addWidget(self.idle_frame)

        self.live_frame = QFrame()
        self.live_frame.setObjectName("liveFrame")
        live_layout = QVBoxLayout(self.live_frame)
        live_layout.setContentsMargins(0, 6, 0, 6)
        live_layout.setSpacing(10)

        self.top_rule = QFrame()
        self.top_rule.setObjectName("liveRule")
        self.top_rule.setFixedHeight(1)
        live_layout.addWidget(self.top_rule)

        self.subtitle_box = QFrame()
        self.subtitle_box.setObjectName("subtitleBox")
        subtitle_layout = QVBoxLayout(self.subtitle_box)
        subtitle_layout.setContentsMargins(34, 18, 34, 16)
        subtitle_layout.setSpacing(8)

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
        self.subtitle_box.setMinimumHeight(170)
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
        self.status_label.setFont(self._make_ui_font(13))
        self.status_label.setMaximumWidth(560)
        footer_row.addWidget(self.status_label, stretch=1)

        self.stop_button = QPushButton("STOP")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.clicked.connect(self._on_start_stop_clicked)
        self.stop_button.setMinimumSize(128, 42)
        self.stop_button.setIcon(self._make_status_dot_icon("#ff4a6a"))
        self.stop_button.setIconSize(QSize(9, 9))
        footer_row.addWidget(self.stop_button, alignment=Qt.AlignmentFlag.AlignRight)

        self.tools_frame = QFrame()
        self.tools_frame.setObjectName("toolsFrame")
        layout.addWidget(self.tools_frame)

        self.debug_bar = QHBoxLayout(self.tools_frame)
        self.debug_bar.setContentsMargins(14, 12, 14, 12)
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

        self.minimize_button = QPushButton("Min")
        self.minimize_button.clicked.connect(self.showMinimized)
        self.debug_bar.addWidget(self.minimize_button)

        self.resize_grip = QSizeGrip(panel)
        self.resize_grip.setObjectName("resizeGrip")
        self.resize_grip.setFixedSize(18, 18)
        self.resize_grip.raise_()

        subtitle_curr_font = self._make_monospace_font(
            read_int_env("SUBTITLE_FONT_SIZE", self.DEFAULT_SUBTITLE_FONT_SIZE),
            bold=True,
        )
        subtitle_curr_size = max(22, min(subtitle_curr_font.pointSize(), 30))
        self.subtitle_curr_label.setFont(self._make_ui_font(subtitle_curr_size, bold=True))
        self.subtitle_prev_label.setFont(self._make_ui_font(max(15, subtitle_curr_size - 11)))

        self._install_shortcuts()

    def _apply_window_style(self) -> None:
        self.setWindowTitle(f"{self._brand_name} - Universal Real-Time Audio Translator")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMinimumSize(760, 166)
        self.resize(890, 172)

        self.setStyleSheet(
            """
            #overlayPanel {
                background-color: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(52, 53, 58, 232),
                    stop:0.52 rgba(43, 44, 49, 228),
                    stop:1 rgba(36, 37, 41, 232)
                );
                border: 1px solid rgba(188, 193, 204, 70);
                border-radius: 26px;
            }
            #brandLabel {
                color: rgba(219, 222, 230, 192);
                letter-spacing: 2.7px;
                padding-left: 4px;
            }
            #iconButton {
                min-width: 28px;
                min-height: 24px;
                max-height: 24px;
                border-radius: 8px;
                background-color: transparent;
                color: rgba(194, 200, 212, 132);
                border: none;
                padding: 0px 4px;
                font-size: 13px;
            }
            #iconButton:hover {
                background-color: rgba(117, 124, 138, 44);
            }
            #iconButton:checked {
                background-color: rgba(111, 120, 136, 74);
                color: rgba(239, 243, 250, 196);
            }
            #idleFrame {
                background-color: transparent;
            }
            #startButton {
                background-color: rgba(84, 88, 97, 118);
                color: rgba(229, 233, 240, 206);
                border: 1px solid rgba(196, 204, 217, 74);
                border-radius: 19px;
                font-size: 15px;
                font-weight: 500;
                letter-spacing: 2.6px;
                padding: 4px 18px;
            }
            #startButton:hover {
                background-color: rgba(96, 102, 114, 142);
            }
            #liveRule {
                background-color: rgba(170, 178, 192, 34);
                border: none;
            }
            #liveFrame {
                background-color: transparent;
            }
            #subtitleBox {
                background-color: rgba(18, 19, 24, 148);
                border: 1px solid rgba(193, 200, 211, 40);
                border-radius: 22px;
            }
            #subtitlePrev {
                color: rgba(214, 219, 227, 114);
                font-weight: 500;
            }
            #subtitleCurr {
                color: rgba(249, 250, 252, 244);
                font-weight: 700;
            }
            #subtitleCurr[preview="true"] {
                color: rgba(221, 226, 235, 162);
                font-weight: 600;
            }
            #liveTranscript {
                background-color: rgba(14, 15, 19, 172);
                color: rgba(231, 236, 244, 220);
                border: 1px solid rgba(187, 194, 207, 54);
                border-radius: 14px;
                padding: 10px;
            }
            #historyFrame {
                background-color: rgba(13, 15, 19, 188);
                border: 1px solid rgba(175, 186, 203, 50);
                border-radius: 16px;
            }
            #historyTitle {
                color: rgba(176, 197, 227, 192);
            }
            #historyView {
                background-color: transparent;
                color: rgba(190, 204, 224, 188);
                border: none;
            }
            #toolsFrame {
                background-color: rgba(14, 15, 19, 126);
                border: 1px solid rgba(183, 190, 202, 40);
                border-radius: 16px;
            }
            #liveDot {
                background-color: #38d66f;
                border-radius: 6px;
            }
            #liveLabel {
                color: rgba(138, 220, 173, 190);
                letter-spacing: 3.2px;
            }
            #statusLabel {
                color: rgba(214, 219, 229, 128);
                font-size: 11px;
            }
            #stopButton {
                background-color: rgba(92, 95, 104, 118);
                color: rgba(248, 186, 198, 224);
                border: 1px solid rgba(225, 168, 180, 116);
                border-radius: 18px;
                font-size: 12px;
                font-weight: 500;
                letter-spacing: 1.5px;
                padding: 5px 16px;
            }
            #stopButton:hover {
                background-color: rgba(106, 91, 98, 156);
            }
            #debugLabel {
                color: rgba(155, 232, 184, 214);
                font-size: 12px;
            }
            #shortcutHint {
                color: rgba(176, 188, 206, 138);
            }
            #footerFrame {
                background-color: transparent;
            }
            #resizeGrip {
                background-color: transparent;
                border-right: 1px solid rgba(198, 205, 217, 110);
                border-bottom: 1px solid rgba(198, 205, 217, 110);
                border-bottom-right-radius: 6px;
            }
            QLabel, QCheckBox {
                color: rgba(214, 222, 236, 196);
            }
            QPushButton {
                background-color: rgba(67, 73, 84, 136);
                color: rgba(229, 235, 244, 220);
                border: 1px solid rgba(186, 194, 206, 64);
                border-radius: 12px;
                padding: 4px 12px;
                min-height: 30px;
            }
            QPushButton:hover {
                background-color: rgba(88, 96, 110, 156);
            }
            """
        )

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

        self.subtitle_box.setVisible(self._listening)
        self.transcript_view.setVisible(self._listening and self._tools_panel_open and self._subtitle_mode == "list")

        self.live_dot.setVisible(self._listening)
        self.live_label.setVisible(self._listening)
        self.stop_button.setVisible(self._listening)
        self.footer_frame.setVisible(self._listening)

        self.status_label.setVisible(self._should_show_status_label(self.status_label.text()))
        self.history_frame.setVisible(self._listening and self._tools_panel_open and self._history_expanded)
        show_advanced_tools = self._listening and self._tools_panel_open
        self.tools_frame.setVisible(show_advanced_tools)
        self.debug_label.setVisible(show_advanced_tools and self._debug_enabled)

        self.start_stop_button.setText("START")
        self.user_button.setChecked(self._tools_panel_open)

        if self._listening:
            self.setMinimumHeight(294)
            if self.height() < 294:
                self.resize(max(self.width(), 890), 304)
        else:
            self.setMinimumHeight(196)
            if self.height() < 196:
                self.resize(max(self.width(), 890), 196)

    def _on_start_stop_clicked(self) -> None:
        next_state = not self._listening
        self.set_listening(next_state)
        self.toggle_listening.emit(next_state)

    def _on_history_toggled(self, checked: bool) -> None:
        self._history_expanded = checked
        self._refresh_state_ui()

    def _toggle_debug_tools(self) -> None:
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
        if hasattr(self, "resize_grip") and hasattr(self, "_panel"):
            panel_rect = self._panel.rect()
            x = panel_rect.width() - self.resize_grip.width() - 10
            y = panel_rect.height() - self.resize_grip.height() - 10
            self.resize_grip.move(x, y)

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
        curr_text = self._subtitle_curr_text
        curr_preview = False

        if preview_active and not curr_text:
            curr_text = self._subtitle_preview_text
            curr_preview = True

        self.subtitle_prev_label.setVisible(prev_visible)
        self.subtitle_prev_label.setText(self._subtitle_prev_text if prev_visible else "")
        self.subtitle_curr_label.setText(curr_text)
        self.subtitle_curr_label.setProperty("preview", curr_preview)
        self.subtitle_curr_label.style().unpolish(self.subtitle_curr_label)
        self.subtitle_curr_label.style().polish(self.subtitle_curr_label)

    def _reset_live_subtitles(self) -> None:
        self._subtitle_prev_text = ""
        self._subtitle_curr_text = ""
        self._subtitle_preview_text = ""
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
        return self._tools_panel_open or self._debug_enabled or "error" in normalized

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
        font.setFamilies(["Avenir Next", "Helvetica Neue", "Inter", "Arial", "Sans"])
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
