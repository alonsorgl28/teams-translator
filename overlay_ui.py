from __future__ import annotations

import os
from collections import deque
from typing import Optional

from PyQt6.QtCore import QPoint, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
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

from config_utils import read_bool_env, read_int_env


class OverlayWindow(QWidget):
    DRAG_ZONE_HEIGHT = 56
    DEFAULT_FULL_TRANSCRIPT_MAX_SEGMENTS = 500
    MONOSPACE_FONT_FAMILIES = ["Menlo", "Consolas", "Courier New", "Monospace"]

    toggle_listening = pyqtSignal(bool)
    copy_requested = pyqtSignal()
    export_requested = pyqtSignal(str)
    clear_requested = pyqtSignal()
    save_session_changed = pyqtSignal(bool)
    debug_toggled = pyqtSignal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._drag_offset: Optional[QPoint] = None
        self._listening = False
        max_segments = read_int_env("FULL_TRANSCRIPT_MAX_SEGMENTS", self.DEFAULT_FULL_TRANSCRIPT_MAX_SEGMENTS)
        self.full_transcript_buffer: deque[str] = deque(maxlen=max_segments)
        self._debug_enabled = False
        self._subtitle_mode = (os.getenv("SUBTITLE_MODE") or "list").strip().lower()
        self._subtitle_max_line_chars = read_int_env("SUBTITLE_MAX_LINE_CHARS", 42)
        self._subtitle_max_lines = read_int_env("SUBTITLE_MAX_LINES", 2)
        self._subtitle_update_ms = read_int_env("SUBTITLE_UPDATE_MS", 280)
        self._subtitle_show_previous = read_bool_env("SUBTITLE_SHOW_PREVIOUS_LINE", True)
        self._overlay_show_timestamps = read_bool_env("OVERLAY_SHOW_TIMESTAMPS", False)
        self._cinema_pending_text: list[str] = []
        self._subtitle_prev_text = ""
        self._subtitle_curr_text = ""
        self._last_subtitle_norm = ""
        self._display_timer = QTimer(self)
        self._display_timer.setSingleShot(True)
        self._display_timer.timeout.connect(self._flush_cinema_text)

        self._build_ui()
        self._apply_window_style()

    @property
    def save_session_enabled(self) -> bool:
        return self.save_session_checkbox.isChecked()

    def append_segment(self, text: str) -> None:
        cleaned = (text or "").strip()
        if not cleaned:
            return

        self.full_transcript_buffer.append(cleaned)
        if self._subtitle_mode == "cinema" and self._listening:
            display_text = self._strip_timestamp(cleaned)
            if not display_text:
                return
            self._cinema_pending_text.append(display_text)
            if not self._display_timer.isActive():
                self._display_timer.start(self._subtitle_update_ms)
            return

        self._append_to_list_view(self._display_line(cleaned))

    def clear_segments(self) -> None:
        self._cinema_pending_text.clear()
        self._display_timer.stop()
        self._reset_live_subtitles()
        self.transcript_view.clear()

    def get_full_transcript_text(self) -> str:
        return "\n".join(self.full_transcript_buffer)

    def set_listening(self, listening: bool) -> None:
        was_listening = self._listening
        self._listening = listening
        self.start_stop_button.setText("Stop Listening" if listening else "Start Listening")
        if self._subtitle_mode != "cinema":
            return
        if was_listening and not listening:
            self._flush_cinema_text()
            self.subtitle_box.hide()
            self.transcript_view.show()
            self._render_full_history()
        elif not was_listening and listening:
            # Keep full history for export/copy, but show only live subtitle block while listening.
            self._reset_live_subtitles()
            self.transcript_view.clear()
            self.transcript_view.hide()
            self.subtitle_box.show()

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def set_debug_mode(self, enabled: bool) -> None:
        self._debug_enabled = enabled
        self.debug_checkbox.blockSignals(True)
        self.debug_checkbox.setChecked(enabled)
        self.debug_checkbox.blockSignals(False)
        self.debug_label.setVisible(enabled)
        if not enabled:
            self.debug_label.setText("")

    def set_debug_info(self, text: str, color: str) -> None:
        if not self._debug_enabled:
            return
        self.debug_label.setText(text)
        self.debug_label.setStyleSheet(f"color: {color};")

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        panel = QFrame()
        panel.setObjectName("overlayPanel")
        root.addWidget(panel)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        layout.addLayout(controls)

        self.start_stop_button = QPushButton("Start Listening")
        self.start_stop_button.clicked.connect(self._on_start_stop_clicked)
        controls.addWidget(self.start_stop_button)

        copy_button = QPushButton("Copy All")
        copy_button.clicked.connect(self.copy_requested.emit)
        controls.addWidget(copy_button)

        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.clear_requested.emit)
        controls.addWidget(clear_button)

        minimize_button = QPushButton("Minimize")
        minimize_button.clicked.connect(self.showMinimized)
        controls.addWidget(minimize_button)

        export_button = QPushButton("Export .txt")
        export_button.clicked.connect(self._on_export_clicked)
        controls.addWidget(export_button)

        self.save_session_checkbox = QCheckBox("Save Session")
        self.save_session_checkbox.stateChanged.connect(
            lambda state: self.save_session_changed.emit(state == Qt.CheckState.Checked.value)
        )
        controls.addWidget(self.save_session_checkbox)

        self.debug_checkbox = QCheckBox("Debug")
        self.debug_checkbox.stateChanged.connect(
            lambda state: self.debug_toggled.emit(state == Qt.CheckState.Checked.value)
        )
        controls.addWidget(self.debug_checkbox)

        self.subtitle_box = QFrame()
        self.subtitle_box.setObjectName("subtitleBox")
        subtitle_layout = QVBoxLayout(self.subtitle_box)
        subtitle_layout.setContentsMargins(18, 12, 18, 12)
        subtitle_layout.setSpacing(4)

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
        self.subtitle_box.hide()
        layout.addWidget(self.subtitle_box)

        self.transcript_view = QTextEdit()
        self.transcript_view.setReadOnly(True)
        self.transcript_view.setAcceptRichText(False)
        self.transcript_view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.transcript_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(self.transcript_view)

        self.status_label = QLabel("Idle")
        self.debug_label = QLabel("")
        self.debug_label.setVisible(False)
        self.debug_label.setFont(self._make_monospace_font(11))

        status_row = QHBoxLayout()
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        status_row.addWidget(self.debug_label, alignment=Qt.AlignmentFlag.AlignRight)
        self.size_grip = QSizeGrip(panel)
        status_row.addWidget(self.size_grip, alignment=Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        layout.addLayout(status_row)

        default_font = 20 if self._subtitle_mode == "cinema" else 18
        history_font_size = read_int_env("OVERLAY_FONT_SIZE", default_font)
        self.transcript_view.setFont(self._make_monospace_font(history_font_size))

        subtitle_curr_font = self._make_monospace_font(
            read_int_env("SUBTITLE_FONT_SIZE", max(20, history_font_size + 1)),
            bold=True,
        )
        self.subtitle_curr_label.setFont(subtitle_curr_font)

        subtitle_prev_font = self._make_monospace_font(max(14, subtitle_curr_font.pointSize() - 4))
        self.subtitle_prev_label.setFont(subtitle_prev_font)

    def _apply_window_style(self) -> None:
        self.setWindowTitle("Teams Realtime Translator")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMinimumSize(600, 220)
        self.resize(980, 360)

        self.setStyleSheet(
            """
            #overlayPanel {
                background-color: rgba(28, 28, 28, 180);
                border: 1px solid rgba(255, 255, 255, 48);
                border-radius: 12px;
            }
            #subtitleBox {
                background-color: rgba(0, 0, 0, 170);
                border: 1px solid rgba(255, 255, 255, 32);
                border-radius: 10px;
            }
            #subtitlePrev {
                color: rgba(255, 255, 255, 185);
                padding: 0px 6px;
            }
            #subtitleCurr {
                color: rgba(255, 255, 255, 255);
                padding: 0px 6px;
            }
            QTextEdit {
                background-color: rgba(43, 43, 43, 0);
                color: white;
                border: none;
                padding: 8px;
            }
            QLabel, QCheckBox {
                color: white;
            }
            QPushButton {
                background-color: rgba(70, 70, 70, 220);
                color: white;
                border: 1px solid rgba(255, 255, 255, 50);
                border-radius: 8px;
                padding: 6px 9px;
            }
            QPushButton:hover {
                background-color: rgba(88, 88, 88, 220);
            }
            """
        )

    def _is_user_at_bottom(self) -> bool:
        scrollbar = self.transcript_view.verticalScrollBar()
        return scrollbar.value() >= (scrollbar.maximum() - 2)

    def _on_start_stop_clicked(self) -> None:
        next_state = not self._listening
        self.set_listening(next_state)
        self.toggle_listening.emit(next_state)

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

    def _append_to_list_view(self, line: str) -> None:
        should_scroll = self._is_user_at_bottom()
        if self.transcript_view.toPlainText():
            self.transcript_view.insertPlainText("\n")
        self.transcript_view.insertPlainText(line)
        if should_scroll or self._listening:
            cursor = self.transcript_view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.transcript_view.setTextCursor(cursor)
            self.transcript_view.ensureCursorVisible()

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
        if not self.full_transcript_buffer:
            self.transcript_view.clear()
            return
        visible_history = [self._display_line(line) for line in self.full_transcript_buffer]
        self.transcript_view.setPlainText("\n".join(visible_history))
        cursor = self.transcript_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.transcript_view.setTextCursor(cursor)
        self.transcript_view.ensureCursorVisible()

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
        prev_visible = self._subtitle_show_previous and bool(self._subtitle_prev_text.strip())
        self.subtitle_prev_label.setVisible(prev_visible)
        self.subtitle_prev_label.setText(self._subtitle_prev_text if prev_visible else "")
        self.subtitle_curr_label.setText(self._with_current_marker(self._subtitle_curr_text))

    def _reset_live_subtitles(self) -> None:
        self._subtitle_prev_text = ""
        self._subtitle_curr_text = ""
        self._last_subtitle_norm = ""
        self.subtitle_prev_label.clear()
        self.subtitle_curr_label.clear()
        self.subtitle_prev_label.setVisible(False)

    @staticmethod
    def _with_current_marker(text: str) -> str:
        lines = text.splitlines()
        if not lines:
            return ""
        lines[0] = f">> {lines[0]}"
        return "\n".join(lines)

    @staticmethod
    def _normalize_for_compare(text: str) -> str:
        normalized = text.lower().strip()
        normalized = " ".join(normalized.split())
        return normalized

    @classmethod
    def _make_monospace_font(cls, point_size: int, bold: bool = False) -> QFont:
        font = QFont()
        font.setFamilies(cls.MONOSPACE_FONT_FAMILIES)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(point_size)
        font.setBold(bold)
        return font
