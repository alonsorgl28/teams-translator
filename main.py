from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Optional

from dotenv import load_dotenv
from PyQt6.QtWidgets import QApplication
from qasync import QEventLoop

from audio_listener import AudioChunk, SystemAudioListener
from overlay_ui import OverlayWindow
from transcription_service import WhisperTranscriptionService
from translation_service import TechnicalTranslationService


class RollingTranscriptBuffer:
    def __init__(self, window_minutes: int = 60) -> None:
        self._window = timedelta(minutes=window_minutes)
        self._entries: deque[tuple[datetime, str]] = deque()

    def add(self, timestamp: datetime, text: str) -> None:
        self._entries.append((timestamp, text))
        self._prune(timestamp)

    def clear(self) -> None:
        self._entries.clear()

    def to_text(self) -> str:
        now = datetime.now()
        self._prune(now)
        return "\n".join(text for _, text in self._entries)

    def _prune(self, now: datetime) -> None:
        cutoff = now - self._window
        while self._entries and self._entries[0][0] < cutoff:
            self._entries.popleft()


class MeetingTranslatorController:
    SUPPORTED_LANG_CODES = {
        "en",
        "english",
        "pt",
        "pt-br",
        "portuguese",
        "zh",
        "zh-cn",
        "zh-tw",
        "chinese",
        "mandarin",
        "hi",
        "hindi",
    }

    def __init__(self, ui: OverlayWindow) -> None:
        self.ui = ui
        self.loop = asyncio.get_event_loop()
        self.audio_queue: asyncio.Queue[AudioChunk] = asyncio.Queue(maxsize=16)
        self.text_queue: asyncio.Queue[
            tuple[AudioChunk, str, str, float, datetime, datetime]
        ] = asyncio.Queue(maxsize=24)
        self.listener = SystemAudioListener(
            loop=self.loop,
            output_queue=self.audio_queue,
            chunk_seconds=2.0,
            chunk_step_seconds=self._read_float_env("CHUNK_STEP_SECONDS", 1.5),
            preferred_device=os.getenv("SYSTEM_AUDIO_DEVICE"),
        )
        self.transcriber: Optional[WhisperTranscriptionService] = None
        self.translator: Optional[TechnicalTranslationService] = None
        self.buffer = RollingTranscriptBuffer(window_minutes=60)
        self.saved_session_text: list[str] = []

        self.running = False
        self.transcribe_task: Optional[asyncio.Task[None]] = None
        self.translate_task: Optional[asyncio.Task[None]] = None
        self.debug_enabled = os.getenv("DEBUG_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}
        self.latency_window: deque[float] = deque(maxlen=10)
        self.chunks_processed = 0
        self.transcription_errors = 0
        self.translation_errors = 0
        self.last_api_time = 0.0
        self._last_rendered_normalized = ""

        self.ui.toggle_listening.connect(self._on_toggle_listening)
        self.ui.copy_requested.connect(self._on_copy_requested)
        self.ui.export_requested.connect(self._on_export_requested)
        self.ui.clear_requested.connect(self._on_clear_requested)
        self.ui.save_session_changed.connect(self._on_save_session_changed)
        self.ui.debug_toggled.connect(self._on_debug_toggled)
        self.ui.set_debug_mode(self.debug_enabled)

        self.ui.set_status("Idle. Select VB-Cable/BlackHole as the system output device.")

    @staticmethod
    def _read_float_env(name: str, default: float) -> float:
        raw = (os.getenv(name) or "").strip()
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError:
            return default
        return value if value > 0 else default

    async def start(self) -> None:
        if self.running:
            return
        try:
            self._ensure_services()
            self._last_rendered_normalized = ""
            self.listener.start()
        except Exception as exc:  # noqa: BLE001 - service startup boundary
            self.ui.set_status(f"Startup error: {exc}")
            self.ui.set_listening(False)
            return

        self.running = True
        self.transcribe_task = asyncio.create_task(self._transcription_worker_loop(), name="transcription-worker")
        self.translate_task = asyncio.create_task(self._translation_worker_loop(), name="translation-worker")
        self.ui.set_status("Listening to system audio...")

    async def stop(self) -> None:
        if not self.running:
            self.ui.set_listening(False)
            return
        self.running = False
        self.listener.stop()

        for task in (self.transcribe_task, self.translate_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self.transcribe_task = None
        self.translate_task = None

        self.ui.set_listening(False)
        self.ui.set_status("Stopped.")

    def shutdown_sync(self) -> None:
        self.listener.stop()
        for task in (self.transcribe_task, self.translate_task):
            if task and not task.done():
                task.cancel()

    async def _transcription_worker_loop(self) -> None:
        while self.running:
            try:
                chunk = await self.audio_queue.get()
                transcription_start_ts = datetime.now()
                started = perf_counter()
                transcribed = await self.transcriber.transcribe(chunk.wav_bytes)  # type: ignore[union-attr]
                transcription_end_ts = datetime.now()
                transcription_time = perf_counter() - started
                if self.debug_enabled:
                    logging.info(
                        "debug_transcription captured_at=%s transcription_start=%s transcription_end=%s transcription_s=%.3f",
                        chunk.captured_at.isoformat(timespec="milliseconds"),
                        transcription_start_ts.isoformat(timespec="milliseconds"),
                        transcription_end_ts.isoformat(timespec="milliseconds"),
                        transcription_time,
                    )

                source_text = transcribed.text.strip()
                if not source_text:
                    continue

                await self.text_queue.put(
                    (
                        chunk,
                        source_text,
                        transcribed.language or "auto",
                        transcription_time,
                        transcription_start_ts,
                        transcription_end_ts,
                    )
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - runtime boundary
                self.transcription_errors += 1
                if self.debug_enabled:
                    self._update_debug_panel(language="auto")
                error_text = str(exc)
                self.ui.set_status(f"Transcription error: {error_text}")
                if "Authentication failed" in error_text or "401" in error_text or "403" in error_text:
                    # Stop workers/listener on invalid credentials to avoid request spam.
                    asyncio.create_task(self.stop())
                    break

    async def _translation_worker_loop(self) -> None:
        while self.running:
            try:
                (
                    chunk,
                    source_text,
                    source_language,
                    transcription_time,
                    transcription_start_ts,
                    transcription_end_ts,
                ) = await self.text_queue.get()
                translation_start_ts = datetime.now()
                started = perf_counter()
                translated = await self.translator.translate_text(source_text)  # type: ignore[union-attr]
                if self.translator.last_error:  # type: ignore[union-attr]
                    self.translation_errors += 1
                    if self.debug_enabled:
                        logging.warning("debug_translation_fallback reason=%s", self.translator.last_error)
                translation_end_ts = datetime.now()
                translation_time = perf_counter() - started
                if self.debug_enabled:
                    logging.info(
                        "debug_translation captured_at=%s transcription_start=%s transcription_end=%s "
                        "translation_start=%s translation_end=%s transcription_s=%.3f translation_s=%.3f",
                        chunk.captured_at.isoformat(timespec="milliseconds"),
                        transcription_start_ts.isoformat(timespec="milliseconds"),
                        transcription_end_ts.isoformat(timespec="milliseconds"),
                        translation_start_ts.isoformat(timespec="milliseconds"),
                        translation_end_ts.isoformat(timespec="milliseconds"),
                        transcription_time,
                        translation_time,
                    )

                timestamp = datetime.now()
                rendered = f"[{timestamp:%H:%M:%S}] {translated}"
                if self._is_duplicate_segment(rendered):
                    continue
                self.buffer.add(timestamp, rendered)

                if self.ui.save_session_enabled:
                    self.saved_session_text.append(rendered)

                self.ui.append_segment(rendered)
                latency = (datetime.now() - chunk.captured_at).total_seconds()
                self.chunks_processed += 1
                self.latency_window.append(latency)
                self.last_api_time = transcription_time + translation_time
                if self.debug_enabled:
                    self._update_debug_panel(language=source_language, api_time=self.last_api_time)
                    logging.info(
                        "debug_latency captured_at=%s latency_s=%.3f api_s=%.3f chunks=%d",
                        chunk.captured_at.isoformat(timespec="milliseconds"),
                        latency,
                        self.last_api_time,
                        self.chunks_processed,
                    )
                lang_label = source_language or "auto"
                if lang_label.lower() not in self.SUPPORTED_LANG_CODES:
                    self.ui.set_status(f"Live (detected {lang_label}) -> es | {latency:.1f}s")
                else:
                    self.ui.set_status(f"Live ({lang_label}) -> es | {latency:.1f}s")
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - runtime boundary
                self.translation_errors += 1
                if self.debug_enabled:
                    self._update_debug_panel(language="auto")
                self.ui.set_status(f"Translation error: {exc}")

    def _ensure_services(self) -> None:
        if self.transcriber is None:
            self.transcriber = WhisperTranscriptionService()
        if self.translator is None:
            self.translator = TechnicalTranslationService()

    def _on_toggle_listening(self, should_listen: bool) -> None:
        asyncio.create_task(self.start() if should_listen else self.stop())

    def _on_copy_requested(self) -> None:
        payload = self.ui.get_full_transcript_text()
        QApplication.clipboard().setText(payload)
        self.ui.set_status("Full transcript copied to clipboard.")

    def _on_export_requested(self, path: str) -> None:
        payload = self._full_transcript_text()
        file_path = Path(path)
        file_path.write_text(payload, encoding="utf-8")
        self.ui.set_status(f"Exported transcript: {file_path.name}")

    def _on_clear_requested(self) -> None:
        self._last_rendered_normalized = ""
        self.ui.clear_segments()
        self.ui.set_status("Visible overlay text cleared. Buffer kept in memory.")

    def _on_save_session_changed(self, enabled: bool) -> None:
        if enabled:
            self.ui.set_status("Save Session enabled (translated text only).")
            return
        self.saved_session_text.clear()
        self.ui.set_status("Save Session disabled. Stored session text cleared.")

    def _on_debug_toggled(self, enabled: bool) -> None:
        self.debug_enabled = enabled
        self.ui.set_debug_mode(enabled)
        if enabled:
            self._update_debug_panel(language="auto")

    def _full_transcript_text(self) -> str:
        if self.ui.save_session_enabled:
            return "\n".join(self.saved_session_text)
        return self.ui.get_full_transcript_text() or self.buffer.to_text()

    def _update_debug_panel(self, language: str, api_time: Optional[float] = None) -> None:
        if not self.debug_enabled:
            return
        avg_latency = sum(self.latency_window) / len(self.latency_window) if self.latency_window else 0.0
        api_time = api_time if api_time is not None else self.last_api_time
        color = "#2ecc71"
        if avg_latency >= 4.0:
            color = "#e74c3c"
        elif avg_latency >= 2.5:
            color = "#f1c40f"

        debug_text = (
            f"Avg {avg_latency:.2f}s | Lang {language} | API {api_time:.2f}s | "
            f"Chunks {self.chunks_processed} | Err T {self.transcription_errors} / X {self.translation_errors}"
        )
        self.ui.set_debug_info(debug_text, color)

    def _is_duplicate_segment(self, rendered_text: str) -> bool:
        normalized = re.sub(r"^\[[0-9:]{8}\]\s*", "", rendered_text).strip().lower()
        normalized = re.sub(r"[^\w\s]", "", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        if not normalized:
            return True
        previous = self._last_rendered_normalized
        if previous:
            if normalized == previous:
                return True
            shorter = min(len(normalized), len(previous))
            longer = max(len(normalized), len(previous))
            very_similar_size = shorter / longer >= 0.8 if longer else False
            if very_similar_size and (normalized in previous or previous in normalized):
                return True
        self._last_rendered_normalized = normalized
        return False


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    overlay = OverlayWindow()
    controller = MeetingTranslatorController(overlay)
    app.aboutToQuit.connect(controller.shutdown_sync)
    overlay.show()

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
