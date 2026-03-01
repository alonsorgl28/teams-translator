from __future__ import annotations

import asyncio
import difflib
import logging
import os
import re
import sys
from collections import Counter, deque
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Optional

from dotenv import load_dotenv
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from qasync import QEventLoop

from audio_listener import AudioChunk, StreamingAudioFrame, SystemAudioListener
from config_utils import read_bool_env, read_float_env, read_int_env
from metrics_reporter import SessionMetricsReporter
from overlay_ui import OverlayWindow
from transcription_service import RealtimeTranscriptionEvent, RealtimeTranscriptionService, WhisperTranscriptionService
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


class OverlayPreviewRunner:
    PREVIEW_TICK_MS = 1100
    PREVIEW_SEGMENTS = (
        "Quizás podemos hablar de los dos competidores actuales.",
        "Codex tiende a leer más contexto y eso mejora la calidad del código.",
        "Opus suele responder más rápido y con un estilo más conversacional.",
        "En tareas complejas, ambos funcionan bien si defines objetivos claros.",
        "La diferencia práctica aparece en persistencia, velocidad y estilo de respuesta.",
        "Si priorizas latencia baja, este modo usa segmentos cortos pero legibles.",
    )
    PREVIEW_LATENCIES = (1.5, 1.7, 1.9, 2.1, 2.3, 2.0)

    def __init__(self, ui: OverlayWindow) -> None:
        self.ui = ui
        self._running = False
        self._segment_idx = 0
        self._latency_idx = 0
        self._ticker = QTimer(ui)
        self._ticker.timeout.connect(self._emit_next_segment)

        self.ui.toggle_listening.connect(self._on_toggle_listening)
        self.ui.copy_requested.connect(self._on_copy_requested)
        self.ui.export_requested.connect(self._on_export_requested)
        self.ui.clear_requested.connect(self._on_clear_requested)
        self.ui.debug_toggled.connect(self._on_debug_toggled)

    def start(self) -> None:
        self._running = True
        self.ui.set_debug_mode(True)
        self.ui.set_listening(True)
        self.ui.set_status("Preview mode activo: simulando subtítulos en tiempo real.")
        self._ticker.start(self.PREVIEW_TICK_MS)
        self._emit_next_segment()

    def stop(self) -> None:
        self._running = False
        self._ticker.stop()
        self.ui.set_listening(False)
        self.ui.set_status("Preview detenido.")

    def _on_toggle_listening(self, should_listen: bool) -> None:
        if should_listen:
            if not self._running:
                self._running = True
            if not self._ticker.isActive():
                self._ticker.start(self.PREVIEW_TICK_MS)
            self.ui.set_status("Preview mode activo: simulando subtítulos en tiempo real.")
            return
        self._running = False
        self._ticker.stop()
        self.ui.set_status("Preview detenido.")

    def _on_copy_requested(self) -> None:
        QApplication.clipboard().setText(self.ui.get_full_transcript_text())
        self.ui.set_status("Preview: transcript copiado al portapapeles.")

    def _on_export_requested(self, path: str) -> None:
        Path(path).write_text(self.ui.get_full_transcript_text(), encoding="utf-8")
        self.ui.set_status(f"Preview: exportado en {Path(path).name}.")

    def _on_clear_requested(self) -> None:
        self.ui.clear_segments()
        self.ui.set_status("Preview: texto visible limpiado.")

    def _on_debug_toggled(self, enabled: bool) -> None:
        self.ui.set_debug_mode(enabled)

    def _emit_next_segment(self) -> None:
        if not self._running:
            return
        segment = self.PREVIEW_SEGMENTS[self._segment_idx % len(self.PREVIEW_SEGMENTS)]
        stamp = datetime.now().strftime("%M:%S")
        self.ui.append_segment(f"[{stamp}] {segment}")
        self._segment_idx += 1
        self._update_runtime_labels()

    def _update_runtime_labels(self) -> None:
        latency = self.PREVIEW_LATENCIES[self._latency_idx % len(self.PREVIEW_LATENCIES)]
        self._latency_idx += 1
        self.ui.set_status(f"Live preview (english -> es) | {latency:.1f}s")
        color = "#2ecc71" if latency < 2.2 else "#f1c40f"
        self.ui.set_debug_info(f"AVG 1.92s | P95 2.45s | Issue 0.0%", color)


class MeetingTranslatorController:
    RECENT_RENDERED_MAXLEN = 5
    DUPLICATE_SEQUENCE_RATIO = 0.995
    DUPLICATE_MAX_WORD_DELTA = 0
    MIN_WORDS_ON_AGE_FLUSH = 2
    STALE_EMIT_RELAX_FACTOR = 2.0
    FIRST_EMIT_MIN_CHARS = 4
    MIN_STALENESS_SECONDS_LIVE = 6.0
    MIN_CHUNK_STEP_SECONDS_LIVE = 0.85
    MAX_CHUNK_SECONDS_LIVE = 1.0
    STARTUP_LISTENER_VALIDATION_SECONDS = 0.8
    PROVISIONAL_PREVIEW_MIN_WORDS = 2
    SOURCE_TRANSLATION_MIN_WORDS = 4
    SOURCE_TRANSLATION_MIN_CHARS = 18
    SOURCE_TRANSLATION_MAX_AGE_SECONDS = 0.95
    SOURCE_TRANSLATION_FIRST_AGE_SECONDS = 0.3
    SOURCE_TRANSLATION_BACKLOG_MIN_WORDS = 2
    SOURCE_TRANSLATION_FORCE_AFTER_FRAGMENTS = 2
    SOURCE_TRANSLATION_FORCE_FRAGMENT_MIN_WORDS = 3
    SOURCE_INCOMPLETE_TRAILING_TOKENS = {
        "and",
        "or",
        "but",
        "the",
        "a",
        "an",
        "to",
        "of",
        "for",
        "with",
        "that",
        "than",
        "into",
        "from",
        "about",
        "como",
        "pero",
        "para",
        "con",
        "sin",
        "que",
        "de",
        "del",
        "la",
        "el",
        "los",
        "las",
        "un",
        "una",
    }

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

    def __init__(self, ui: OverlayWindow, loop: asyncio.AbstractEventLoop) -> None:
        self.ui = ui
        self.loop = loop
        self.source_language = (os.getenv("SOURCE_LANGUAGE") or "Auto-detect").strip() or "Auto-detect"
        self.target_language = (os.getenv("TARGET_LANGUAGE") or "Spanish").strip() or "Spanish"
        self.literal_complete_mode = read_bool_env("LITERAL_COMPLETE_MODE", False)
        self.short_timestamps = read_bool_env("SHORT_TIMESTAMPS", True)
        default_audio_q = 24 if self.literal_complete_mode else 8
        default_text_q = 32 if self.literal_complete_mode else 10
        self.audio_queue: asyncio.Queue[AudioChunk] = asyncio.Queue(
            maxsize=read_int_env("AUDIO_QUEUE_MAXSIZE", default_audio_q)
        )
        self.stream_audio_queue: asyncio.Queue[StreamingAudioFrame] = asyncio.Queue(
            maxsize=read_int_env("STREAM_AUDIO_QUEUE_MAXSIZE", 96)
        )
        self.text_queue: asyncio.Queue[
            tuple[AudioChunk, str, str, float, datetime, datetime]
        ] = asyncio.Queue(maxsize=read_int_env("TEXT_QUEUE_MAXSIZE", default_text_q))
        default_chunk_seconds = 1.8 if self.literal_complete_mode else 1.6
        chunk_seconds = read_float_env("CHUNK_SECONDS", default_chunk_seconds)
        if not self.literal_complete_mode:
            chunk_seconds = min(chunk_seconds, self.MAX_CHUNK_SECONDS_LIVE)
        default_chunk_step = min(1.2 if self.literal_complete_mode else 1.0, chunk_seconds)
        configured_chunk_step = read_float_env("CHUNK_STEP_SECONDS", default_chunk_step)
        if not self.literal_complete_mode:
            # Overlap that is too aggressive can outpace API throughput and create stale drops.
            configured_chunk_step = max(configured_chunk_step, min(chunk_seconds, self.MIN_CHUNK_STEP_SECONDS_LIVE))
        self.realtime_transcription_enabled = read_bool_env("REALTIME_TRANSCRIPTION_ENABLED", False)
        self.listener = SystemAudioListener(
            loop=self.loop,
            output_queue=self.audio_queue,
            chunk_seconds=chunk_seconds,
            chunk_step_seconds=configured_chunk_step,
            preferred_device=os.getenv("SYSTEM_AUDIO_DEVICE"),
            drop_oldest_on_full=not self.literal_complete_mode,
            stream_output_queue=self.stream_audio_queue if self.realtime_transcription_enabled else None,
        )
        default_skip = 999999 if self.literal_complete_mode else 2
        self.max_audio_backlog_before_skip = read_int_env("MAX_AUDIO_BACKLOG_BEFORE_SKIP", default_skip)
        self.max_text_backlog_before_skip = read_int_env(
            "MAX_TEXT_BACKLOG_BEFORE_SKIP",
            read_int_env("MAX_BACKLOG_BEFORE_SKIP", default_skip),
        )
        self.merge_min_words = read_int_env("MERGE_MIN_WORDS", 7 if self.literal_complete_mode else 5)
        self.merge_max_words = read_int_env("MERGE_MAX_WORDS", 52 if self.literal_complete_mode else 24)
        self.merge_flush_seconds = read_float_env("MERGE_FLUSH_SECONDS", 2.8 if self.literal_complete_mode else 1.2)
        self.min_emit_words = read_int_env("MIN_EMIT_WORDS", 4 if self.literal_complete_mode else 3)
        self.max_pending_render_age_seconds = read_float_env(
            "MAX_PENDING_RENDER_AGE_SECONDS",
            2.2 if self.literal_complete_mode else 1.0,
        )
        configured_staleness = read_float_env(
            "MAX_SEGMENT_STALENESS_SECONDS",
            8.0 if self.literal_complete_mode else 6.0,
        )
        if self.literal_complete_mode:
            self.max_segment_staleness_seconds = configured_staleness
        else:
            self.max_segment_staleness_seconds = max(configured_staleness, self.MIN_STALENESS_SECONDS_LIVE)
        self.max_emit_staleness_seconds = self.max_segment_staleness_seconds * max(
            self.STALE_EMIT_RELAX_FACTOR,
            2.0,
        )
        self.transcriber: Optional[WhisperTranscriptionService] = None
        self.realtime_transcriber: Optional[RealtimeTranscriptionService] = None
        self.translator: Optional[TechnicalTranslationService] = None
        self.buffer = RollingTranscriptBuffer(window_minutes=60)
        self.saved_session_text: list[str] = []

        self._running_lock = asyncio.Lock()
        self.running = False
        self.transcribe_task: Optional[asyncio.Task[None]] = None
        self.translate_task: Optional[asyncio.Task[None]] = None
        self.realtime_audio_task: Optional[asyncio.Task[None]] = None
        self._toggle_task: Optional[asyncio.Task[None]] = None
        self.debug_enabled = os.getenv("DEBUG_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}
        self.filter_gibberish = read_bool_env("FILTER_GIBBERISH", True)
        self.latency_window: deque[float] = deque(maxlen=10)
        self.chunks_processed = 0
        self.transcription_errors = 0
        self.translation_errors = 0
        self.translation_fallbacks = 0
        self.skipped_audio_chunks = 0
        self.skipped_text_chunks = 0
        self.skipped_stale_segments = 0
        self.last_api_time = 0.0
        self.metrics_min_text_len = read_int_env("METRICS_MIN_TEXT_LEN", 8)
        self.metrics_reporter = SessionMetricsReporter(
            enabled=read_bool_env("METRICS_ENABLED", True),
            output_path=os.getenv("METRICS_OUTPUT_PATH", "./reports/session_metrics.jsonl"),
            summary_path=os.getenv("METRICS_SUMMARY_PATH", "./reports/session_summary.json"),
            append_mode=read_bool_env("METRICS_APPEND_MODE", False),
        )
        self._last_rendered_normalized = ""
        self._recent_rendered_normalized: deque[str] = deque(maxlen=self.RECENT_RENDERED_MAXLEN)
        self._last_source_text = ""
        self._last_emitted_text = ""
        self._pending_render_text = ""
        self._pending_captured_at: Optional[datetime] = None
        self._pending_metrics_data: Optional[dict[str, Any]] = None
        self._pending_source_text = ""
        self._pending_source_captured_at: Optional[datetime] = None
        self._pending_source_language = "auto"
        self._pending_source_metrics_data: Optional[dict[str, Any]] = None
        self._pending_source_fragment_count = 0
        self._source_preview_active = False
        self._using_realtime_transcription = False

        self.ui.toggle_listening.connect(self._on_toggle_listening)
        self.ui.copy_requested.connect(self._on_copy_requested)
        self.ui.export_requested.connect(self._on_export_requested)
        self.ui.clear_requested.connect(self._on_clear_requested)
        self.ui.save_session_changed.connect(self._on_save_session_changed)
        self.ui.debug_toggled.connect(self._on_debug_toggled)
        self.ui.language_settings_changed.connect(self._on_language_settings_changed)
        self.ui.audio_source_changed.connect(self._on_audio_source_changed)
        self.ui.set_debug_mode(self.debug_enabled)

        self.ui.set_status(
            f"Idle. Target language: {self.target_language}. Select VB-Cable/BlackHole as system output."
        )

    async def start(self) -> None:
        async with self._running_lock:
            if self.running:
                return
            self.running = True
        try:
            self._ensure_services()
            self._clear_runtime_queues()
            self._last_rendered_normalized = ""
            self._recent_rendered_normalized.clear()
            self._last_source_text = ""
            self._last_emitted_text = ""
            self._pending_render_text = ""
            self._pending_captured_at = None
            self.translation_fallbacks = 0
            self._pending_metrics_data = None
            self._reset_pending_source_buffer()
            self._source_preview_active = False
            self._using_realtime_transcription = False
            if self.transcriber is not None:
                self.transcriber.reset_context()
            if self.translator is not None and hasattr(self.translator, "reset_context"):
                self.translator.reset_context()
            if self.realtime_transcriber is not None:
                self.realtime_transcriber.reset_context()
                try:
                    await self.realtime_transcriber.start()
                    self._using_realtime_transcription = True
                except Exception as exc:  # noqa: BLE001 - graceful batch fallback
                    logging.warning("Realtime transcription unavailable, falling back to batch: %s", exc)
                    self._using_realtime_transcription = False
            self.metrics_reporter.start_session()
            self.listener.start()
        except Exception as exc:  # noqa: BLE001 - service startup boundary
            async with self._running_lock:
                self.running = False
            self.ui.set_status(f"Startup error: {exc}")
            self.ui.set_listening(False)
            return

        if self._using_realtime_transcription:
            self.realtime_audio_task = asyncio.create_task(
                self._realtime_audio_sender_loop(),
                name="realtime-audio-sender",
            )
            self.transcribe_task = asyncio.create_task(
                self._realtime_transcription_worker_loop(),
                name="realtime-transcription-worker",
            )
        else:
            self.transcribe_task = asyncio.create_task(self._transcription_worker_loop(), name="transcription-worker")
        self.translate_task = asyncio.create_task(self._translation_worker_loop(), name="translation-worker")
        self.ui.set_status("Listening to system audio...")
        await asyncio.sleep(self.STARTUP_LISTENER_VALIDATION_SECONDS)
        if not self.listener.is_running:
            await self.stop()
            self.ui.set_status(
                "Audio device not found or failed to start. Please check your audio settings (BlackHole/VB-Cable)."
            )
            return

    async def stop(self) -> None:
        async with self._running_lock:
            if not self.running:
                self.ui.set_listening(False)
                return
            self.running = False
        self.listener.stop()

        for task in (self.transcribe_task, self.translate_task, self.realtime_audio_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self.transcribe_task = None
        self.translate_task = None
        self.realtime_audio_task = None
        if self.realtime_transcriber is not None and self._using_realtime_transcription:
            await self.realtime_transcriber.stop()
        self._using_realtime_transcription = False
        self._flush_pending_render(language="auto")
        self._clear_runtime_queues()
        self._reset_pending_source_buffer()
        self._source_preview_active = False
        self.ui.clear_live_preview()
        summary = self.metrics_reporter.finalize_session()
        if self.debug_enabled and summary:
            logging.info("metrics_session_summary %s", summary)

        self.ui.set_listening(False)
        self.ui.set_status("Stopped.")

    def shutdown_sync(self) -> None:
        self.listener.stop()
        self.metrics_reporter.finalize_session()
        self._clear_runtime_queues()
        if self._toggle_task and not self._toggle_task.done():
            self._toggle_task.cancel()
        for task in (self.transcribe_task, self.translate_task, self.realtime_audio_task):
            if task and not task.done():
                task.cancel()
        if self.realtime_transcriber is not None and self._using_realtime_transcription and self.loop.is_running():
            self.loop.create_task(self.realtime_transcriber.stop())
        self._using_realtime_transcription = False

    async def _transcription_worker_loop(self) -> None:
        while True:
            async with self._running_lock:
                if not self.running:
                    break
            try:
                chunk = await self.audio_queue.get()
                audio_backlog = self.audio_queue.qsize()
                if audio_backlog > self.max_audio_backlog_before_skip:
                    skipped = 0
                    while True:
                        try:
                            chunk = self.audio_queue.get_nowait()
                            skipped += 1
                        except asyncio.QueueEmpty:
                            break
                    self.skipped_audio_chunks += skipped
                    if self.debug_enabled and skipped:
                        logging.info("debug_skip_audio skipped=%d backlog=%d", skipped, audio_backlog)
                if self._drop_stale_chunk(chunk.captured_at, stage="transcription"):
                    continue

                transcription_start_ts = datetime.now()
                started = perf_counter()
                transcribed = await self.transcriber.transcribe(  # type: ignore[union-attr]
                    chunk.wav_bytes,
                    preview_callback=self._handle_transcription_preview,
                )
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

                source_text = self._sanitize_transcribed_text(transcribed.text)
                if not source_text:
                    continue
                self._maybe_show_source_preview(source_text)

                await self._enqueue_translation_item(
                    chunk=chunk,
                    source_text=source_text,
                    source_language=transcribed.language or "auto",
                    transcription_time=transcription_time,
                    transcription_start_ts=transcription_start_ts,
                    transcription_end_ts=transcription_end_ts,
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - runtime boundary
                self.transcription_errors += 1
                self.metrics_reporter.record_error(
                    stage="transcription",
                    error=str(exc),
                    audio_backlog=self._current_audio_backlog(),
                    text_backlog=self.text_queue.qsize(),
                )
                if self.debug_enabled:
                    self._update_debug_panel(language="auto")
                error_text = str(exc)
                self.ui.set_status(f"Transcription error: {error_text}")
                if "Authentication failed" in error_text or "401" in error_text or "403" in error_text:
                    # Stop workers/listener on invalid credentials to avoid request spam.
                    self._schedule_toggle(False)
                    break

    async def _realtime_audio_sender_loop(self) -> None:
        while True:
            async with self._running_lock:
                if not self.running:
                    break
            try:
                frame = await self.stream_audio_queue.get()
                if not self._using_realtime_transcription or self.realtime_transcriber is None:
                    continue
                await self.realtime_transcriber.append_audio(
                    samples=frame.samples,
                    sample_rate=frame.sample_rate,
                    captured_at=frame.captured_at,
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - realtime boundary
                self.transcription_errors += 1
                self.metrics_reporter.record_error(
                    stage="transcription",
                    error=str(exc),
                    audio_backlog=self._current_audio_backlog(),
                    text_backlog=self.text_queue.qsize(),
                )
                await self._fallback_to_batch_transcription(f"Realtime audio error: {exc}")
                break

    async def _realtime_transcription_worker_loop(self) -> None:
        while True:
            async with self._running_lock:
                if not self.running:
                    break
            try:
                if self.realtime_transcriber is None:
                    await asyncio.sleep(0.05)
                    continue
                event = await self.realtime_transcriber.get_event()
                if event.kind == "preview":
                    preview_text = self._clean_transcription_noise(event.text)
                    if preview_text:
                        self._source_preview_active = True
                        self.ui.set_live_preview(preview_text)
                    continue
                if event.kind == "error":
                    self.transcription_errors += 1
                    self.metrics_reporter.record_error(
                        stage="transcription",
                        error=event.error,
                        audio_backlog=self._current_audio_backlog(),
                        text_backlog=self.text_queue.qsize(),
                    )
                    await self._fallback_to_batch_transcription(f"Realtime transcription error: {event.error}")
                    break
                if event.kind != "final":
                    continue
                source_text = self._sanitize_transcribed_text(event.text)
                if not source_text:
                    continue
                chunk = AudioChunk(
                    captured_at=event.captured_at,
                    duration_s=0.0,
                    wav_bytes=b"",
                )
                transcription_start_ts = event.captured_at
                transcription_end_ts = datetime.now()
                await self._enqueue_translation_item(
                    chunk=chunk,
                    source_text=source_text,
                    source_language=event.language or "auto",
                    transcription_time=event.latency_s,
                    transcription_start_ts=transcription_start_ts,
                    transcription_end_ts=transcription_end_ts,
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - realtime boundary
                self.transcription_errors += 1
                self.metrics_reporter.record_error(
                    stage="transcription",
                    error=str(exc),
                    audio_backlog=self._current_audio_backlog(),
                    text_backlog=self.text_queue.qsize(),
                )
                await self._fallback_to_batch_transcription(f"Realtime transcription error: {exc}")
                break

    async def _fallback_to_batch_transcription(self, reason: str) -> None:
        if not self._using_realtime_transcription:
            self.ui.set_status(reason)
            return

        self._using_realtime_transcription = False
        self._source_preview_active = False
        self.ui.clear_live_preview()
        self.ui.set_status(f"{reason}. Falling back to batch transcription.")

        current_task = asyncio.current_task()
        if self.realtime_audio_task is not None and self.realtime_audio_task is not current_task:
            self.realtime_audio_task.cancel()
            try:
                await self.realtime_audio_task
            except asyncio.CancelledError:
                pass
        self.realtime_audio_task = None

        if self.realtime_transcriber is not None:
            await self.realtime_transcriber.stop()

        if self.transcribe_task is None or self.transcribe_task is current_task or self.transcribe_task.done():
            self.transcribe_task = asyncio.create_task(
                self._transcription_worker_loop(),
                name="transcription-worker",
            )

    async def _translation_worker_loop(self) -> None:
        while True:
            async with self._running_lock:
                if not self.running:
                    break
            try:
                (
                    chunk,
                    source_text,
                    source_language,
                    transcription_time,
                    transcription_start_ts,
                    transcription_end_ts,
                ) = await self.text_queue.get()
                backlog = self.text_queue.qsize()
                audio_backlog_snapshot = self._current_audio_backlog()
                if backlog > self.max_text_backlog_before_skip:
                    skipped = 0
                    while True:
                        try:
                            (
                                chunk,
                                source_text,
                                source_language,
                                transcription_time,
                                transcription_start_ts,
                                transcription_end_ts,
                            ) = self.text_queue.get_nowait()
                            skipped += 1
                        except asyncio.QueueEmpty:
                            break
                    self.skipped_text_chunks += skipped
                    if self.debug_enabled and skipped:
                        logging.info("debug_skip_text skipped=%d backlog=%d", skipped, backlog)
                if self._drop_stale_chunk(chunk.captured_at, stage="translation"):
                    continue

                source_metrics = {
                    "captured_at": chunk.captured_at,
                    "source_language": source_language,
                    "transcription_start_ts": transcription_start_ts,
                    "transcription_end_ts": transcription_end_ts,
                    "translation_start_ts": transcription_end_ts,
                    "translation_end_ts": transcription_end_ts,
                    "transcription_time_s": transcription_time,
                    "translation_time_s": 0.0,
                    "audio_backlog": audio_backlog_snapshot,
                    "text_backlog": backlog,
                    "had_fallback": False,
                    "fallback_reason": "",
                }
                self._buffer_source_fragment(
                    source_text,
                    chunk_captured_at=chunk.captured_at,
                    source_language=source_language,
                    metrics_data=source_metrics,
                )
                if not self._should_translate_pending_source(
                    source_text,
                    backlog=backlog,
                    audio_backlog=audio_backlog_snapshot,
                ):
                    continue

                pending_source = self._consume_pending_source_buffer()
                if pending_source is None:
                    continue

                source_text, source_language, source_metrics = pending_source
                started = perf_counter()
                translation_start_ts = datetime.now()
                translated = await self.translator.translate_text(  # type: ignore[union-attr]
                    source_text,
                    target_language=self.target_language,
                )
                fallback_reason = self.translator.last_error or ""  # type: ignore[union-attr]
                if fallback_reason:
                    self.translation_fallbacks += 1
                    if self.debug_enabled:
                        logging.warning("debug_translation_fallback reason=%s", fallback_reason)
                translation_end_ts = datetime.now()
                translation_time = perf_counter() - started
                source_metrics = dict(source_metrics)
                source_metrics["translation_start_ts"] = translation_start_ts
                source_metrics["translation_end_ts"] = translation_end_ts
                source_metrics["translation_time_s"] = translation_time
                source_metrics["had_fallback"] = bool(fallback_reason)
                source_metrics["fallback_reason"] = fallback_reason
                if self.debug_enabled:
                    logging.info(
                        "debug_translation captured_at=%s transcription_start=%s transcription_end=%s "
                        "translation_start=%s translation_end=%s transcription_s=%.3f translation_s=%.3f",
                        source_metrics["captured_at"].isoformat(timespec="milliseconds"),
                        source_metrics["transcription_start_ts"].isoformat(timespec="milliseconds"),
                        source_metrics["transcription_end_ts"].isoformat(timespec="milliseconds"),
                        translation_start_ts.isoformat(timespec="milliseconds"),
                        translation_end_ts.isoformat(timespec="milliseconds"),
                        float(source_metrics["transcription_time_s"]),
                        translation_time,
                    )

                emitted = self._buffer_or_emit_translation(
                    translated=translated,
                    chunk_captured_at=source_metrics["captured_at"],
                    source_language=source_language,
                    api_time=float(source_metrics["transcription_time_s"]) + translation_time,
                    metrics_data=source_metrics,
                )
                # If fragment was buffered but not emitted yet, keep status responsive.
                if not emitted:
                    self.last_api_time = float(source_metrics["transcription_time_s"]) + translation_time
                    if self.debug_enabled:
                        self._update_debug_panel(language=source_language, api_time=self.last_api_time)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - runtime boundary
                self.translation_errors += 1
                self.metrics_reporter.record_error(
                    stage="translation",
                    error=str(exc),
                    audio_backlog=self._current_audio_backlog(),
                    text_backlog=self.text_queue.qsize(),
                )
                if self.debug_enabled:
                    self._update_debug_panel(language="auto")
                self.ui.set_status(f"Translation error: {exc}")

    def _ensure_services(self) -> None:
        if self.transcriber is None:
            self.transcriber = WhisperTranscriptionService()
        if self.realtime_transcription_enabled and self.realtime_transcriber is None:
            self.realtime_transcriber = RealtimeTranscriptionService()
        if self.translator is None:
            self.translator = TechnicalTranslationService()

    def _clear_runtime_queues(self) -> None:
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        while not self.text_queue.empty():
            try:
                self.text_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        while not self.stream_audio_queue.empty():
            try:
                self.stream_audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def _current_audio_backlog(self) -> int:
        if self._using_realtime_transcription:
            return self.stream_audio_queue.qsize()
        return self.audio_queue.qsize()

    async def _enqueue_translation_item(
        self,
        *,
        chunk: AudioChunk,
        source_text: str,
        source_language: str,
        transcription_time: float,
        transcription_start_ts: datetime,
        transcription_end_ts: datetime,
    ) -> None:
        item = (
            chunk,
            source_text,
            source_language,
            transcription_time,
            transcription_start_ts,
            transcription_end_ts,
        )
        if self.literal_complete_mode:
            await self.text_queue.put(item)
            return
        try:
            self.text_queue.put_nowait(item)
        except asyncio.QueueFull:
            try:
                self.text_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self.text_queue.put_nowait(item)
            except asyncio.QueueFull:
                logging.warning("text_queue remained full after drop; discarding latest transcription item")

    def _sanitize_transcribed_text(self, source_text: str) -> str:
        cleaned = self._clean_transcription_noise((source_text or "").strip())
        if not cleaned:
            return ""
        if self.filter_gibberish and self._looks_gibberish(cleaned):
            if self.debug_enabled:
                logging.info("debug_gibberish_dropped text=%r", cleaned[:120])
            return ""
        cleaned = self._remove_source_overlap(cleaned)
        if not cleaned:
            return ""
        cleaned = self._remove_adjacent_sentence_duplicates(cleaned)
        return cleaned

    async def _handle_transcription_preview(self, preview_text: str) -> None:
        if self.literal_complete_mode:
            return
        cleaned = self._clean_transcription_noise(preview_text)
        if not cleaned:
            return
        self._source_preview_active = True
        self.ui.set_live_preview(cleaned)

    def _on_toggle_listening(self, should_listen: bool) -> None:
        self._schedule_toggle(should_listen)

    def _schedule_toggle(self, should_listen: bool) -> None:
        if self._toggle_task and not self._toggle_task.done():
            self._toggle_task.cancel()
        task = asyncio.create_task(
            self.start() if should_listen else self.stop(),
            name="toggle-listening",
        )
        self._toggle_task = task

        def _finalize(done_task: asyncio.Task[None]) -> None:
            if self._toggle_task is done_task:
                self._toggle_task = None
            try:
                done_task.result()
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001 - task boundary
                self.ui.set_status(f"Toggle error: {exc}")

        task.add_done_callback(_finalize)

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
        self._last_emitted_text = ""
        self._reset_pending_source_buffer()
        self._source_preview_active = False
        self.ui.clear_live_preview()
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

    def _on_language_settings_changed(self, source_language: str, target_language: str) -> None:
        self.source_language = source_language
        self.target_language = target_language
        if self.transcriber is not None:
            self.transcriber.reset_context()
        if self.realtime_transcriber is not None:
            self.realtime_transcriber.reset_context()
        if self.translator is not None:
            if hasattr(self.translator, "reset_context"):
                self.translator.reset_context()
            elif hasattr(self.translator, "clear_context"):
                self.translator.clear_context()
        self.ui.set_status(f"Settings applied: {source_language} -> {target_language}.")

    def _on_audio_source_changed(self, audio_source: str) -> None:
        if self.listener is None:
            return
        selected = (audio_source or "").strip()
        if selected and selected.lower() != "system loopback (default)":
            self.listener._preferred_device = selected
        else:
            self.listener._preferred_device = None
        self.ui.set_status("Audio source updated. Restart listening to apply it.")

    def _full_transcript_text(self) -> str:
        if self.ui.save_session_enabled:
            return "\n".join(self.saved_session_text)
        return self.ui.get_full_transcript_text() or self.buffer.to_text()

    def _update_debug_panel(self, language: str, api_time: Optional[float] = None) -> None:
        if not self.debug_enabled:
            return
        avg_latency = sum(self.latency_window) / len(self.latency_window) if self.latency_window else 0.0
        p95_latency = self._percentile(list(self.latency_window), 0.95)
        metrics_snapshot = self.metrics_reporter.snapshot()
        issue_rate = metrics_snapshot["issue_rate_pct"]
        api_time = api_time if api_time is not None else self.last_api_time
        color = "#2ecc71"
        if p95_latency >= 4.0:
            color = "#e74c3c"
        elif p95_latency >= 2.5:
            color = "#f1c40f"

        del language, api_time
        debug_text = (
            f"AVG {avg_latency:.2f}s | P95 {p95_latency:.2f}s | "
            f"Stale {self.skipped_stale_segments} | Issue {issue_rate:.1f}%"
        )
        self.ui.set_debug_info(debug_text, color)

    def _drop_stale_chunk(self, captured_at: datetime, stage: str) -> bool:
        age_s = (datetime.now() - captured_at).total_seconds()
        threshold_s = self.max_segment_staleness_seconds
        if stage == "emit":
            # Rendering can be safely more tolerant than worker stages.
            threshold_s = self.max_emit_staleness_seconds
        if age_s <= threshold_s:
            return False
        self.skipped_stale_segments += 1
        if self.debug_enabled:
            logging.info(
                "debug_drop_stale stage=%s age_s=%.3f threshold_s=%.3f captured_at=%s",
                stage,
                age_s,
                threshold_s,
                captured_at.isoformat(timespec="milliseconds"),
            )
        return True

    def _is_duplicate_segment(self, rendered_text: str) -> bool:
        normalized = re.sub(r"^\[[0-9:]{5,8}\]\s*", "", rendered_text).strip().lower()
        normalized = re.sub(r"[^\w\s]", "", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        if not normalized:
            return True
        if normalized in self._recent_rendered_normalized:
            return True
        for previous in self._recent_rendered_normalized:
            previous_tokens = previous.split()
            current_tokens = normalized.split()
            if not previous_tokens or not current_tokens:
                continue
            similar_len = abs(len(previous_tokens) - len(current_tokens)) <= self.DUPLICATE_MAX_WORD_DELTA
            if not similar_len:
                continue
            sequence_ratio = difflib.SequenceMatcher(
                None,
                previous_tokens,
                current_tokens,
                autojunk=False,
            ).ratio()
            if sequence_ratio >= self.DUPLICATE_SEQUENCE_RATIO:
                return True
        self._last_rendered_normalized = normalized
        self._recent_rendered_normalized.append(normalized)
        return False

    @staticmethod
    def _percentile(values: list[float], ratio: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        if len(ordered) == 1:
            return ordered[0]
        index = (len(ordered) - 1) * ratio
        lower = int(index)
        upper = min(lower + 1, len(ordered) - 1)
        if lower == upper:
            return ordered[lower]
        weight = index - lower
        return ordered[lower] * (1.0 - weight) + ordered[upper] * weight

    @staticmethod
    def _looks_gibberish(text: str) -> bool:
        normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
        tokens = re.findall(r"[a-z0-9]+", normalized)
        if len(tokens) < 6:
            return False

        counts = Counter(tokens)
        most_common_count = counts.most_common(1)[0][1]
        repeat_ratio = most_common_count / len(tokens)
        unique_ratio = len(counts) / len(tokens)

        long_repeated = re.search(r"\b([a-z]{4,})\b(?:\s+\1\b){2,}", normalized) is not None
        return repeat_ratio >= 0.45 or unique_ratio <= 0.30 or long_repeated

    def _remove_source_overlap(self, source_text: str) -> str:
        cleaned = re.sub(r"\s+", " ", source_text.strip())
        if not cleaned:
            return ""
        previous = self._last_source_text
        if not previous:
            self._last_source_text = cleaned
            return cleaned

        prev_words = previous.split()
        curr_words = cleaned.split()
        max_n = min(len(prev_words), len(curr_words), 18)
        overlap_n = 0
        for n in range(max_n, 2, -1):
            prev_tail = [self._normalize_word_token(token) for token in prev_words[-n:]]
            curr_head = [self._normalize_word_token(token) for token in curr_words[:n]]
            if prev_tail == curr_head:
                overlap_n = n
                break

        if overlap_n and (len(curr_words) - overlap_n) >= 2:
            curr_words = curr_words[overlap_n:]
        deduped = " ".join(curr_words).strip()
        self._last_source_text = cleaned
        if not deduped:
            return ""
        return deduped

    @staticmethod
    def _normalize_word_token(token: str) -> str:
        return re.sub(r"^[^\w]+|[^\w]+$", "", token).lower()

    def _remove_adjacent_sentence_duplicates(self, text: str) -> str:
        parts = re.split(r"([.!?]+)", text)
        if len(parts) <= 1:
            return text.strip()

        rebuilt: list[str] = []
        previous_norm = ""

        i = 0
        while i < len(parts):
            sentence = (parts[i] or "").strip()
            punct = parts[i + 1] if i + 1 < len(parts) else ""
            i += 2
            if not sentence:
                continue
            candidate = f"{sentence}{punct}".strip()
            norm = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", candidate).lower()).strip()
            if norm and norm == previous_norm:
                continue
            rebuilt.append(candidate)
            previous_norm = norm

        return " ".join(rebuilt).strip()

    @staticmethod
    def _clean_transcription_noise(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        if not cleaned:
            return ""
        cleaned = re.sub(r"(https?://\S+|www\.\S+)", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bwww\s*\.?\s*engvid\s*\.?\s*com\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bwww\b\s*\.?\s*\bcom\b", "", cleaned, flags=re.IGNORECASE)
        noise_patterns = (
            r"\baprende\s+ingl[eé]s\s+gratis\b",
            r"\blearn english for free\b",
            r"\blearn more at [\w.-]+\.(?:com|org|net)\b",
            r"\b(?:por favor\s+)?suscr[ií]bete(?:\s+al\s+canal)?\b",
            r"\bengvid\b",
            r"\balaskagranny\b",
            r"\bysgrifennydd\b",
            r"\bpreserve names, brands, acronyms, numbers, and technical terms\b",
            r"\bpreservar nombres, marcas, acr[oó]nimos, n[uú]meros y t[eé]rminos t[eé]cnicos\b",
        )
        for pattern in noise_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(?:suscr[ií]bete|subscribe)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b[\w.-]+\.(?:com|org|net)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = MeetingTranslatorController._limit_repeated_tokens(cleaned, max_repeats=3)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
        return cleaned

    @staticmethod
    def _limit_repeated_tokens(text: str, max_repeats: int = 3) -> str:
        tokens = text.split()
        if not tokens:
            return ""
        filtered: list[str] = []
        last_norm = ""
        run = 0
        for token in tokens:
            norm = re.sub(r"[^\w]+", "", token).lower()
            if norm and norm == last_norm:
                run += 1
            else:
                last_norm = norm
                run = 1
            if not norm or run <= max_repeats:
                filtered.append(token)
        return " ".join(filtered)

    def _buffer_or_emit_translation(
        self,
        translated: str,
        chunk_captured_at: datetime,
        source_language: str,
        api_time: float,
        metrics_data: dict[str, Any],
    ) -> bool:
        fragment = self._normalize_fragment(translated)
        if not fragment:
            return False

        if not self._pending_render_text:
            self._pending_render_text = fragment
            self._pending_captured_at = chunk_captured_at
            self._pending_metrics_data = metrics_data
        else:
            self._pending_render_text = self._merge_fragments(self._pending_render_text, fragment)
            self._pending_metrics_data = self._merge_metrics_data(self._pending_metrics_data, metrics_data)

        if not self._should_emit_pending(fragment):
            return False

        emitted_text = self._pending_render_text
        emitted_captured_at = self._pending_captured_at or chunk_captured_at
        emitted_metrics = self._pending_metrics_data or metrics_data
        self._pending_render_text = ""
        self._pending_captured_at = None
        self._pending_metrics_data = None
        self._emit_segment(emitted_text, emitted_captured_at, source_language, api_time, emitted_metrics)
        return True

    def _emit_segment(
        self,
        translated_text: str,
        captured_at: datetime,
        source_language: str,
        api_time: float,
        metrics_data: Optional[dict[str, Any]] = None,
    ) -> None:
        if self._drop_stale_chunk(captured_at, stage="emit"):
            return
        cleaned = self._trim_overlap_with_previous_emitted(translated_text)
        if not cleaned:
            return
        cleaned = self._remove_adjacent_sentence_duplicates(cleaned)
        if not cleaned:
            return
        self._source_preview_active = False

        timestamp = datetime.now()
        rendered = f"[{self._format_timestamp(timestamp)}] {cleaned}"
        if self._is_duplicate_segment(rendered):
            return
        self.buffer.add(timestamp, rendered)
        if self.ui.save_session_enabled:
            self.saved_session_text.append(rendered)
        self.ui.append_segment(rendered)

        latency = (datetime.now() - captured_at).total_seconds()
        self._record_segment_metrics(
            rendered_text=cleaned,
            captured_at=captured_at,
            source_language=source_language,
            latency=latency,
            api_time=api_time,
            metrics_data=metrics_data,
        )
        self.chunks_processed += 1
        self.latency_window.append(latency)
        self.last_api_time = api_time
        if self.debug_enabled:
            self._update_debug_panel(language=source_language, api_time=self.last_api_time)
            logging.info(
                "debug_latency captured_at=%s latency_s=%.3f api_s=%.3f chunks=%d",
                captured_at.isoformat(timespec="milliseconds"),
                latency,
                self.last_api_time,
                self.chunks_processed,
            )
        lang_label = source_language or "auto"
        target_code = self._target_language_code(self.target_language)
        if lang_label.lower() not in self.SUPPORTED_LANG_CODES:
            self.ui.set_status(f"Live (detected {lang_label}) -> {target_code} | {latency:.1f}s")
        else:
            self.ui.set_status(f"Live ({lang_label}) -> {target_code} | {latency:.1f}s")

    def _flush_pending_render(self, language: str) -> None:
        pending = self._pending_render_text.strip()
        if not pending:
            return
        captured_at = self._pending_captured_at or datetime.now()
        pending_metrics = self._pending_metrics_data or {}
        self._pending_render_text = ""
        self._pending_captured_at = None
        self._pending_metrics_data = None
        self._emit_segment(pending, captured_at, language, self.last_api_time, pending_metrics)

    def _maybe_show_source_preview(self, source_text: str) -> None:
        if self.literal_complete_mode:
            return
        preview_text = self._normalize_fragment(source_text)
        if len(re.findall(r"\b\w+\b", preview_text)) < self.PROVISIONAL_PREVIEW_MIN_WORDS:
            return
        self._source_preview_active = True
        self.ui.set_live_preview(preview_text)

    def _buffer_source_fragment(
        self,
        source_text: str,
        *,
        chunk_captured_at: datetime,
        source_language: str,
        metrics_data: dict[str, Any],
    ) -> None:
        fragment = self._normalize_fragment(source_text)
        if not fragment:
            return
        if not self._pending_source_text:
            self._pending_source_text = fragment
            self._pending_source_captured_at = chunk_captured_at
            self._pending_source_language = source_language or "auto"
            self._pending_source_metrics_data = dict(metrics_data)
            self._pending_source_fragment_count = 1
        else:
            self._pending_source_text = self._merge_fragments(self._pending_source_text, fragment)
            self._pending_source_language = source_language or self._pending_source_language or "auto"
            self._pending_source_metrics_data = self._merge_metrics_data(self._pending_source_metrics_data, metrics_data)
            self._pending_source_fragment_count += 1
        self._maybe_show_source_preview(self._pending_source_text)

    def _consume_pending_source_buffer(self) -> Optional[tuple[str, str, dict[str, Any]]]:
        pending = self._pending_source_text.strip()
        if not pending:
            return None
        language = self._pending_source_language or "auto"
        metrics_data = dict(self._pending_source_metrics_data or {})
        self._reset_pending_source_buffer()
        return pending, language, metrics_data

    def _reset_pending_source_buffer(self) -> None:
        self._pending_source_text = ""
        self._pending_source_captured_at = None
        self._pending_source_language = "auto"
        self._pending_source_metrics_data = None
        self._pending_source_fragment_count = 0

    def _should_translate_pending_source(self, latest_fragment: str, *, backlog: int, audio_backlog: int) -> bool:
        pending = self._pending_source_text.strip()
        if not pending:
            return False
        word_count = len(re.findall(r"\b\w+\b", pending))
        if word_count == 0:
            return False
        incomplete_tail = self._ends_with_incomplete_connector(pending) or re.search(r"[,:;/\\-]\s*$", latest_fragment)
        age_s = None
        if self._pending_source_captured_at is not None:
            age_s = (datetime.now() - self._pending_source_captured_at).total_seconds()
        if self.chunks_processed == 0 and age_s is not None and not incomplete_tail:
            if word_count >= self.MIN_WORDS_ON_AGE_FLUSH and age_s >= self.SOURCE_TRANSLATION_FIRST_AGE_SECONDS:
                return True
        if re.search(r"[.!?]\s*$", pending) is not None and word_count >= self.min_emit_words:
            return True
        if (
            self._pending_source_fragment_count >= self.SOURCE_TRANSLATION_FORCE_AFTER_FRAGMENTS
            and not incomplete_tail
            and (
                word_count >= self.SOURCE_TRANSLATION_FORCE_FRAGMENT_MIN_WORDS
                or len(pending) >= self.SOURCE_TRANSLATION_MIN_CHARS
            )
        ):
            return True
        if backlog > 0 or audio_backlog > 0:
            return word_count >= self.SOURCE_TRANSLATION_BACKLOG_MIN_WORDS or len(pending) >= self.SOURCE_TRANSLATION_MIN_CHARS
        if age_s is not None:
            age_threshold = (
                self.SOURCE_TRANSLATION_FIRST_AGE_SECONDS if self.chunks_processed == 0 else self.SOURCE_TRANSLATION_MAX_AGE_SECONDS
            )
            if age_s >= age_threshold:
                return word_count >= self.MIN_WORDS_ON_AGE_FLUSH or len(pending) >= self.SOURCE_TRANSLATION_MIN_CHARS
        if incomplete_tail:
            return False
        if word_count >= max(self.merge_min_words + 1, self.SOURCE_TRANSLATION_MIN_WORDS):
            return True
        return len(pending) >= max(self.SOURCE_TRANSLATION_MIN_CHARS, 24)

    def _ends_with_incomplete_connector(self, text: str) -> bool:
        last_word_match = re.search(r"(\w+)\W*$", text.lower())
        if not last_word_match:
            return False
        return last_word_match.group(1) in self.SOURCE_INCOMPLETE_TRAILING_TOKENS

    @staticmethod
    def _normalize_fragment(text: str) -> str:
        cleaned = (text or "").strip()
        cleaned = re.sub(r"^\.\.\.\s*", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    @staticmethod
    def _target_language_code(language: str) -> str:
        normalized = (language or "").strip().lower()
        mapping = {
            "spanish": "es",
            "english": "en",
            "portuguese (brazil)": "pt-br",
            "mandarin chinese (simplified)": "zh-cn",
            "hindi": "hi",
        }
        return mapping.get(normalized, normalized or "target")

    def _merge_fragments(self, current: str, incoming: str) -> str:
        if not current:
            return incoming
        if not incoming:
            return current
        if incoming.lower() in current.lower():
            return current
        if current.lower() in incoming.lower():
            return incoming

        current_words = current.split()
        incoming_words = incoming.split()
        max_n = min(len(current_words), len(incoming_words), 12)
        overlap_n = 0
        for n in range(max_n, 2, -1):
            left = [self._normalize_word_token(token) for token in current_words[-n:]]
            right = [self._normalize_word_token(token) for token in incoming_words[:n]]
            if left == right:
                overlap_n = n
                break
        if overlap_n:
            tail = " ".join(incoming_words[overlap_n:]).strip()
            if not tail:
                return current
            return f"{current} {tail}".strip()

        if current.endswith(("-", "/", "(", "[")):
            return f"{current}{incoming}"
        return f"{current} {incoming}".strip()

    @staticmethod
    def _merge_metrics_data(
        previous: Optional[dict[str, Any]],
        incoming: dict[str, Any],
    ) -> dict[str, Any]:
        if not previous:
            return dict(incoming)
        merged = dict(previous)
        merged["captured_at"] = min(
            previous.get("captured_at", incoming.get("captured_at")),
            incoming.get("captured_at", previous.get("captured_at")),
        )
        merged["transcription_start_ts"] = min(
            previous.get("transcription_start_ts", incoming.get("transcription_start_ts")),
            incoming.get("transcription_start_ts", previous.get("transcription_start_ts")),
        )
        merged["transcription_end_ts"] = max(
            previous.get("transcription_end_ts", incoming.get("transcription_end_ts")),
            incoming.get("transcription_end_ts", previous.get("transcription_end_ts")),
        )
        merged["translation_start_ts"] = min(
            previous.get("translation_start_ts", incoming.get("translation_start_ts")),
            incoming.get("translation_start_ts", previous.get("translation_start_ts")),
        )
        merged["translation_end_ts"] = max(
            previous.get("translation_end_ts", incoming.get("translation_end_ts")),
            incoming.get("translation_end_ts", previous.get("translation_end_ts")),
        )
        merged["transcription_time_s"] = float(previous.get("transcription_time_s", 0.0)) + float(
            incoming.get("transcription_time_s", 0.0)
        )
        merged["translation_time_s"] = float(previous.get("translation_time_s", 0.0)) + float(
            incoming.get("translation_time_s", 0.0)
        )
        merged["audio_backlog"] = max(int(previous.get("audio_backlog", 0)), int(incoming.get("audio_backlog", 0)))
        merged["text_backlog"] = max(int(previous.get("text_backlog", 0)), int(incoming.get("text_backlog", 0)))
        merged["had_fallback"] = bool(previous.get("had_fallback", False) or incoming.get("had_fallback", False))
        merged["fallback_reason"] = incoming.get("fallback_reason") or previous.get("fallback_reason", "")
        merged["source_language"] = incoming.get("source_language") or previous.get("source_language", "auto")
        return merged

    def _record_segment_metrics(
        self,
        rendered_text: str,
        captured_at: datetime,
        source_language: str,
        latency: float,
        api_time: float,
        metrics_data: Optional[dict[str, Any]],
    ) -> None:
        if not self.metrics_reporter.enabled:
            return
        if len(rendered_text.strip()) < self.metrics_min_text_len:
            return
        data = dict(metrics_data or {})
        data.setdefault("captured_at", captured_at)
        data.setdefault("source_language", source_language)
        data.setdefault("transcription_start_ts", captured_at)
        data.setdefault("transcription_end_ts", captured_at)
        data.setdefault("translation_start_ts", captured_at)
        data.setdefault("translation_end_ts", datetime.now())
        data.setdefault("transcription_time_s", 0.0)
        data.setdefault("translation_time_s", 0.0)
        data.setdefault("audio_backlog", self._current_audio_backlog())
        data.setdefault("text_backlog", self.text_queue.qsize())
        data.setdefault("had_fallback", False)
        data.setdefault("fallback_reason", "")
        payload = {
            "event_type": "segment",
            "recorded_at": datetime.now().isoformat(timespec="milliseconds"),
            "captured_at": data["captured_at"].isoformat(timespec="milliseconds"),
            "source_language": data["source_language"] or "auto",
            "transcription_start": data["transcription_start_ts"].isoformat(timespec="milliseconds"),
            "transcription_end": data["transcription_end_ts"].isoformat(timespec="milliseconds"),
            "translation_start": data["translation_start_ts"].isoformat(timespec="milliseconds"),
            "translation_end": data["translation_end_ts"].isoformat(timespec="milliseconds"),
            "transcription_time_s": float(data["transcription_time_s"]),
            "translation_time_s": float(data["translation_time_s"]),
            "api_time_s": api_time,
            "latency_total_s": latency,
            "audio_backlog": int(data["audio_backlog"]),
            "text_backlog": int(data["text_backlog"]),
            "text_length": len(rendered_text),
            "had_fallback": bool(data["had_fallback"]),
            "fallback_reason": str(data["fallback_reason"] or ""),
        }
        self.metrics_reporter.record_segment(payload)

    def _trim_overlap_with_previous_emitted(self, translated_text: str) -> str:
        cleaned = re.sub(r"\s+", " ", translated_text.strip())
        if not cleaned:
            return ""
        previous = self._last_emitted_text
        if not previous:
            self._last_emitted_text = cleaned
            return cleaned
        if cleaned.lower() == previous.lower():
            return ""

        prev_words = previous.split()
        curr_words = cleaned.split()
        max_n = min(len(prev_words), len(curr_words), 14)
        overlap_n = 0
        for n in range(max_n, 2, -1):
            left = [self._normalize_word_token(token) for token in prev_words[-n:]]
            right = [self._normalize_word_token(token) for token in curr_words[:n]]
            if left == right:
                overlap_n = n
                break
        if overlap_n and (len(curr_words) - overlap_n) >= 2:
            curr_words = curr_words[overlap_n:]

        trimmed = " ".join(curr_words).strip()
        if not trimmed:
            return cleaned if len(cleaned.split()) >= 2 else ""
        self._last_emitted_text = trimmed
        return trimmed

    def _should_emit_pending(self, latest_fragment: str) -> bool:
        pending = self._pending_render_text.strip()
        if not pending:
            return False
        word_count = len(re.findall(r"\b\w+\b", pending))
        sentence_end = re.search(r"[.!?]\s*$", pending) is not None
        target_words = max(self.merge_min_words, self.min_emit_words)
        if self._source_preview_active and word_count >= self.MIN_WORDS_ON_AGE_FLUSH:
            return True
        if self._pending_captured_at:
            age_s = (datetime.now() - self._pending_captured_at).total_seconds()
            # Hard upper bound for on-screen delay while listening.
            if age_s >= self.max_pending_render_age_seconds:
                if word_count >= self.MIN_WORDS_ON_AGE_FLUSH:
                    return True
                # Keep startup from staying blank for long periods.
                if self.chunks_processed == 0 and len(pending) >= self.FIRST_EMIT_MIN_CHARS:
                    return True
                return False
        if self.literal_complete_mode:
            # Strict mode: avoid cutting lines; emit mostly on sentence endings.
            if sentence_end:
                return word_count >= max(self.min_emit_words, self.merge_min_words // 2)
            if word_count >= self.merge_max_words:
                return True
            if self._pending_captured_at:
                age_s = (datetime.now() - self._pending_captured_at).total_seconds()
                return age_s >= self.merge_flush_seconds and word_count >= max(self.min_emit_words, self.merge_min_words // 2)
            return False
        if self._pending_captured_at:
            age_s = (datetime.now() - self._pending_captured_at).total_seconds()
            if age_s >= self.merge_flush_seconds and word_count >= self.MIN_WORDS_ON_AGE_FLUSH:
                return True
        if word_count >= self.merge_max_words:
            return True
        if sentence_end:
            return word_count >= self.min_emit_words
        if re.search(r"[,:;]\s*$", latest_fragment):
            return False
        return word_count >= target_words and len(pending) >= 48

    def _format_timestamp(self, timestamp: datetime) -> str:
        return timestamp.strftime("%M:%S" if self.short_timestamps else "%H:%M:%S")


def main() -> None:
    load_dotenv()
    log_level_name = (os.getenv("LOG_LEVEL", "INFO") or "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    logging.basicConfig(level=log_level, format="%(asctime)s %(levelname)s %(message)s")
    preview_mode = "--preview-ui" in sys.argv
    qt_args = [arg for arg in sys.argv if arg != "--preview-ui"]

    app = QApplication(qt_args)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    overlay = OverlayWindow()
    overlay.show()
    if preview_mode:
        preview = OverlayPreviewRunner(overlay)
        app.aboutToQuit.connect(preview.stop)
        preview.start()
    else:
        controller = MeetingTranslatorController(overlay, loop)
        app.aboutToQuit.connect(controller.shutdown_sync)

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
