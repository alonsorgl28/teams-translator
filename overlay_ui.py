from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
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


class OverlayWindow(QWidget):
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
        self.full_transcript_buffer: list[str] = []
        self._debug_enabled = False

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

        should_scroll = self._is_user_at_bottom()
        if self.transcript_view.toPlainText():
            self.transcript_view.insertPlainText("\n")
        self.transcript_view.insertPlainText(cleaned)

        if should_scroll:
            cursor = self.transcript_view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.transcript_view.setTextCursor(cursor)
            self.transcript_view.ensureCursorVisible()

    def clear_segments(self) -> None:
        self.transcript_view.clear()

    def get_full_transcript_text(self) -> str:
        return "\n".join(self.full_transcript_buffer)

    def set_listening(self, listening: bool) -> None:
        self._listening = listening
        self.start_stop_button.setText("Stop Listening" if listening else "Start Listening")

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

        self.transcript_view = QTextEdit()
        self.transcript_view.setReadOnly(True)
        self.transcript_view.setAcceptRichText(False)
        self.transcript_view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.transcript_view)

        self.status_label = QLabel("Idle")
        self.debug_label = QLabel("")
        self.debug_label.setVisible(False)
        debug_font = QFont("Menlo")
        debug_font.setPointSize(11)
        self.debug_label.setFont(debug_font)

        status_row = QHBoxLayout()
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        status_row.addWidget(self.debug_label, alignment=Qt.AlignmentFlag.AlignRight)
        self.size_grip = QSizeGrip(panel)
        status_row.addWidget(self.size_grip, alignment=Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        layout.addLayout(status_row)

        font = QFont("Menlo")
        font.setPointSize(20)
        self.transcript_view.setFont(font)

    def _apply_window_style(self) -> None:
        self.setWindowTitle("Teams Realtime Translator")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMinimumSize(600, 220)
        self.resize(980, 360)

        self.setStyleSheet(
            """
            #overlayPanel {
                background-color: rgba(43, 43, 43, 153);
                border: 1px solid rgba(255, 255, 255, 48);
                border-radius: 12px;
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
                border-radius: 6px;
                padding: 6px 10px;
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
        self._listening = not self._listening
        self.set_listening(self._listening)
        self.toggle_listening.emit(self._listening)

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
            # Allow drag from top control area only to avoid interfering with resize.
            if event.position().y() <= 56:
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override naming
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override naming
        self._drag_offset = None
        event.accept()
