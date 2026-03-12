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

# macOS: set Qt plugin path before any PyQt6 import so the cocoa plugin is found
# regardless of the terminal context or shell environment.
if sys.platform == "darwin" and "QT_QPA_PLATFORM_PLUGIN_PATH" not in os.environ:
    try:
        import importlib.util as _ilu
        _spec = _ilu.find_spec("PyQt6")
        if _spec and _spec.origin:
            _plugins = Path(_spec.origin).parent / "Qt6" / "plugins" / "platforms"
            if _plugins.is_dir():
                os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(_plugins)
    except Exception:
        pass

from dotenv import load_dotenv
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from qasync import QEventLoop

from audio_listener import AudioChunk, StreamingAudioFrame, SystemAudioListener
from config_utils import read_bool_env, read_float_env, read_int_env
from metrics_reporter import SessionMetricsReporter
from overlay_ui import OverlayWindow
from replay_logger import ReplayEventLogger
from replay_tools import FixtureSpec, SubtitleCue, load_replay_manifest, load_subtitle_cues, match_reference_cue
from segment_quality import SegmentQualityGate, TranslationRoute
from transcription_service import RealtimeTranscriptionService, WhisperTranscriptionService
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
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.ui.get_full_transcript_text())
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
        self.ui.set_debug_info("AVG 1.92s | P95 2.45s | Issue 0.0%", color)


class MeetingTranslatorController:
    RECENT_RENDERED_MAXLEN = 5
    DUPLICATE_SEQUENCE_RATIO = 0.995
    DUPLICATE_MAX_WORD_DELTA = 0
    MIN_WORDS_ON_AGE_FLUSH = 3
    STALE_EMIT_RELAX_FACTOR = 2.0
    FIRST_EMIT_MIN_CHARS = 12
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
    ENGLISH_FUNCTION_WORDS = {
        "the",
        "and",
        "or",
        "with",
        "for",
        "to",
        "of",
        "in",
        "on",
        "is",
        "are",
        "was",
        "were",
        "this",
        "that",
        "it",
        "you",
        "we",
        "they",
        "i",
    }
    SPANISH_FUNCTION_WORDS = {
        "el",
        "la",
        "los",
        "las",
        "de",
        "del",
        "y",
        "con",
        "para",
        "en",
        "que",
        "es",
        "un",
        "una",
        "por",
        "se",
        "como",
        "pero",
        "muy",
        "más",
        "menos",
        "hola",
        "gracias",
        "sí",
        "no",
        "bueno",
        "buena",
        "buen",
    }
    GENERIC_SPANISH_NOISE_PHRASES = (
        "hola mundo",
        "el gato es negro",
        "esto es una prueba",
        "estoy bien",
        "lo siento",
        "hasta pronto",
        "gracias por ver",
    )

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
        # Keep overlay language consistent by default: show only target-language output.
        self.show_source_preview = read_bool_env("SHOW_SOURCE_PREVIEW", False)
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
            tuple[AudioChunk, str, str, str, float, datetime, datetime]
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
        self.validate_api_key_on_start = read_bool_env("VALIDATE_API_KEY_ON_START", False)
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
        self.emit_min_interval_seconds = read_float_env(
            "EMIT_MIN_INTERVAL_SECONDS",
            0.55 if not self.literal_complete_mode else 0.35,
        )
        self.emit_min_chars = read_int_env("EMIT_MIN_CHARS", 56 if not self.literal_complete_mode else 40)
        self.MIN_WORDS_ON_AGE_FLUSH = read_int_env("MIN_WORDS_ON_AGE_FLUSH", self.MIN_WORDS_ON_AGE_FLUSH)
        self.PROVISIONAL_PREVIEW_MIN_WORDS = read_int_env(
            "PROVISIONAL_PREVIEW_MIN_WORDS",
            self.PROVISIONAL_PREVIEW_MIN_WORDS,
        )
        self.SOURCE_TRANSLATION_MIN_WORDS = read_int_env(
            "SOURCE_TRANSLATION_MIN_WORDS",
            self.SOURCE_TRANSLATION_MIN_WORDS,
        )
        self.SOURCE_TRANSLATION_MIN_CHARS = read_int_env(
            "SOURCE_TRANSLATION_MIN_CHARS",
            self.SOURCE_TRANSLATION_MIN_CHARS,
        )
        self.SOURCE_TRANSLATION_MAX_AGE_SECONDS = read_float_env(
            "SOURCE_TRANSLATION_MAX_AGE_SECONDS",
            self.SOURCE_TRANSLATION_MAX_AGE_SECONDS,
        )
        self.SOURCE_TRANSLATION_FIRST_AGE_SECONDS = read_float_env(
            "SOURCE_TRANSLATION_FIRST_AGE_SECONDS",
            self.SOURCE_TRANSLATION_FIRST_AGE_SECONDS,
        )
        self.SOURCE_TRANSLATION_BACKLOG_MIN_WORDS = read_int_env(
            "SOURCE_TRANSLATION_BACKLOG_MIN_WORDS",
            self.SOURCE_TRANSLATION_BACKLOG_MIN_WORDS,
        )
        self.SOURCE_TRANSLATION_FORCE_AFTER_FRAGMENTS = read_int_env(
            "SOURCE_TRANSLATION_FORCE_AFTER_FRAGMENTS",
            self.SOURCE_TRANSLATION_FORCE_AFTER_FRAGMENTS,
        )
        self.SOURCE_TRANSLATION_FORCE_FRAGMENT_MIN_WORDS = read_int_env(
            "SOURCE_TRANSLATION_FORCE_FRAGMENT_MIN_WORDS",
            self.SOURCE_TRANSLATION_FORCE_FRAGMENT_MIN_WORDS,
        )
        self.strict_en_es_source_guard = read_bool_env("STRICT_EN_ES_SOURCE_GUARD", True)
        self.source_strict_min_words = read_int_env("SOURCE_STRICT_MIN_WORDS", 6)
        self.source_strict_max_wait_seconds = read_float_env("SOURCE_STRICT_MAX_WAIT_SECONDS", 1.15)
        self.segment_quality = SegmentQualityGate()
        self.dual_pass_enabled = self.segment_quality.dual_pass_enabled
        self.preview_min_words = self.segment_quality.preview_min_words
        self.preview_max_age_seconds = self.segment_quality.preview_max_age_seconds
        self.commit_min_words = self.segment_quality.commit_min_words
        self.commit_max_age_seconds = self.segment_quality.commit_max_age_seconds
        self.preview_drop_backlog_threshold = read_int_env("PREVIEW_DROP_BACKLOG_THRESHOLD", 1)
        self.benchmark_test_id = (os.getenv("BENCHMARK_TEST_ID") or "").strip()
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
        self.log_rendered_segments = read_bool_env("LOG_RENDERED_SEGMENTS", False)
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
        self.replay_fixture_id = (
            (os.getenv("REPLAY_FIXTURE_ID") or "").strip()
            or self.benchmark_test_id
            or "live_manual"
        )
        self.replay_audio_path = (os.getenv("REPLAY_AUDIO_PATH") or "").strip()
        self.replay_manifest_path = Path(os.getenv("REPLAY_MANIFEST_PATH", "./bench/replay_manifest.yaml"))
        self.replay_events_enabled = read_bool_env("REPLAY_EVENTS_ENABLED", True)
        self.replay_auto_start = read_bool_env("REPLAY_AUTO_START", bool(self.replay_audio_path))
        self.replay_auto_stop_on_complete = read_bool_env("REPLAY_AUTO_STOP_ON_COMPLETE", True)
        self.replay_auto_exit_on_complete = read_bool_env("REPLAY_AUTO_EXIT_ON_COMPLETE", False)
        self.replay_logger = ReplayEventLogger(
            enabled=self.replay_events_enabled,
            output_path=os.getenv("REPLAY_EVENTS_PATH", "./reports/replay_events.jsonl"),
        )
        self._fixture_specs = load_replay_manifest(self.replay_manifest_path)
        self._fixture_spec: Optional[FixtureSpec] = self._fixture_specs.get(self.replay_fixture_id)
        self._reference_cues: list[SubtitleCue] = self._load_reference_cues()
        self._last_rendered_normalized = ""
        self._recent_rendered_normalized: deque[str] = deque(maxlen=self.RECENT_RENDERED_MAXLEN)
        self._last_source_text = ""
        self._last_emitted_text = ""
        self._pending_render_text = ""
        self._pending_captured_at: Optional[datetime] = None
        self._pending_metrics_data: Optional[dict[str, Any]] = None
        self._pending_source_text = ""
        self._pending_source_raw_text = ""
        self._pending_source_captured_at: Optional[datetime] = None
        self._pending_source_language = "auto"
        self._pending_source_metrics_data: Optional[dict[str, Any]] = None
        self._pending_source_fragment_count = 0
        self._pending_render_revision = 0
        self._source_preview_active = False
        self._using_realtime_transcription = False
        self._last_emit_at: Optional[datetime] = None
        self._last_preview_at: Optional[datetime] = None
        self._last_preview_text = ""
        self._api_key_validated = False
        self._session_anchor_at = datetime.now()
        self._replay_completion_handled = False
        self._replay_completion_timer = QTimer(ui)
        self._replay_completion_timer.setInterval(250)
        self._replay_completion_timer.timeout.connect(self._check_replay_completion)

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
        if self.replay_auto_start:
            QTimer.singleShot(150, self._auto_start_replay_session)

    def _auto_start_replay_session(self) -> None:
        if self.running or (self._toggle_task and not self._toggle_task.done()):
            return
        self.ui.set_listening(True)
        self._schedule_toggle(True)

    async def start(self) -> None:
        async with self._running_lock:
            if self.running:
                return
            self.running = True
        try:
            self._ensure_services()
            if self.transcriber is not None and self.validate_api_key_on_start and not self._api_key_validated:
                await self.transcriber.validate_api_key()
                self._api_key_validated = True
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
            self._pending_render_revision = 0
            self._source_preview_active = False
            self._using_realtime_transcription = False
            self._last_emit_at = None
            self._last_preview_at = None
            self._last_preview_text = ""
            self._session_anchor_at = datetime.now()
            self._replay_completion_handled = False
            self._fixture_specs = load_replay_manifest(self.replay_manifest_path)
            self._fixture_spec = self._fixture_specs.get(self.replay_fixture_id)
            self._reference_cues = self._load_reference_cues()
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
            self.replay_logger.start_session(self.replay_fixture_id, started_at=self._session_anchor_at)
            self.listener.start()
            if self.replay_audio_path:
                self._replay_completion_timer.start()
        except Exception as exc:  # noqa: BLE001 - service startup boundary
            async with self._running_lock:
                self.running = False
            error_msg = str(exc)
            _audio_keywords = ("blackhole", "vb-cable", "virtual", "loopback", "audio device", "system_audio_device")
            if any(kw in error_msg.lower() for kw in _audio_keywords):
                self.ui.show_error_dialog(
                    "Audio Device Not Found",
                    "No virtual audio input device was detected.\n\n"
                    "macOS: Install BlackHole 2ch and route system audio through it.\n"
                    "Windows: Install VB-Cable and set 'CABLE Input' as system audio output.\n\n"
                    f"Details: {error_msg}",
                )
                self.ui.set_status("No audio device found. See setup instructions.")
            elif "api key" in error_msg.lower() or "openai_api_key" in error_msg.lower():
                self.ui.show_error_dialog(
                    "API Key Error",
                    f"OpenAI API key issue detected at startup:\n\n{error_msg}\n\n"
                    "Check that OPENAI_API_KEY is set correctly in your .env file.",
                )
                self.ui.set_status("API key error. Check your .env file.")
            else:
                self.ui.set_status(f"Startup error: {error_msg}")
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
            self.ui.show_error_dialog(
                "Audio Device Not Found",
                "The audio listener failed to start.\n\n"
                "macOS: Install BlackHole 2ch and route system audio through it.\n"
                "Windows: Install VB-Cable and set 'CABLE Input' as system audio output.",
            )
            self.ui.set_status("Audio device failed to start. Check your setup.")
            return

    async def stop(self) -> None:
        async with self._running_lock:
            if not self.running:
                self.ui.set_listening(False)
                return
            self.running = False
        self._replay_completion_timer.stop()
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
        self._last_preview_at = None
        self._last_preview_text = ""
        self.ui.clear_live_preview()
        summary = self.metrics_reporter.finalize_session()
        if self.debug_enabled and summary:
            logging.info("metrics_session_summary %s", summary)

        self.ui.set_listening(False)
        self.ui.set_status("Stopped.")

    def shutdown_sync(self) -> None:
        self._replay_completion_timer.stop()
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

                source_text = self._sanitize_transcribed_text(
                    transcribed.text,
                    source_language=transcribed.language or "auto",
                )
                if not source_text:
                    continue
                self._record_replay_asr_event(
                    source_text_raw=transcribed.text,
                    source_text_sanitized=source_text,
                    asr_stage="stable",
                    captured_at=chunk.captured_at,
                    duration_s=chunk.duration_s,
                    source_language=transcribed.language or "auto",
                    latency_s=transcription_time,
                )
                self._maybe_show_source_preview(source_text)

                await self._enqueue_translation_item(
                    chunk=chunk,
                    source_text=source_text,
                    source_text_raw=transcribed.text,
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
                    if not self.show_source_preview:
                        continue
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
                source_text = self._sanitize_transcribed_text(
                    event.text,
                    source_language=event.language or "auto",
                )
                if not source_text:
                    continue
                self._record_replay_asr_event(
                    source_text_raw=event.text,
                    source_text_sanitized=source_text,
                    asr_stage="stable",
                    captured_at=event.captured_at,
                    duration_s=0.0,
                    source_language=event.language or "auto",
                    latency_s=event.latency_s,
                )
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
                    source_text_raw=event.text,
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
                    source_text_raw,
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
                                source_text_raw,
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
                    "audio_duration_s": chunk.duration_s,
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
                    "segment_stage": "preview",
                    "route": "normal",
                    "semantic_score": 0.0,
                    "language_guard_triggered": False,
                    "dropped_reason": "",
                    "fixture_id": self.replay_fixture_id,
                    "source_text_raw": source_text_raw,
                    "source_text_sanitized": source_text,
                    "source_text": source_text,
                    "source_confidence": self.segment_quality.confidence_from_source(source_text),
                    "source_incomplete": False,
                    "mixed_script_detected": False,
                    "non_target_language_detected": False,
                    "translation_too_similar_to_source": False,
                    "semantic_drift_score": 0.0,
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

                source_text, source_text_raw, source_language, source_metrics = pending_source
                source_metrics["source_text_raw"] = source_text_raw
                source_metrics["source_text_sanitized"] = source_text
                started = perf_counter()
                translation_start_ts = datetime.now()
                confidence_score = self.segment_quality.confidence_from_source(source_text)
                translated, route = await self.translator.translate_text_with_route(  # type: ignore[union-attr]
                    source_text,
                    target_language=self.target_language,
                    confidence_score=confidence_score,
                )
                fallback_reason = self.translator.last_error or ""  # type: ignore[union-attr]
                pending_age_s = (datetime.now() - source_metrics["captured_at"]).total_seconds()
                decision = self.segment_quality.decide_commit(
                    source_text=source_text,
                    translated_text=translated,
                    target_language=self.target_language,
                    route=route,
                    pending_age_s=pending_age_s,
                )
                if (
                    decision.stage == "drop"
                    and decision.dropped_reason in {"semantic_low", "language_guard"}
                    and route == "normal"
                ):
                    retry_translated, retry_route = await self.translator.translate_text_with_route(  # type: ignore[union-attr]
                        source_text,
                        target_language=self.target_language,
                        confidence_score=0.0,
                        force_premium=True,
                    )
                    if retry_route == "premium":
                        route = retry_route
                        translated = retry_translated
                        pending_age_s = (datetime.now() - source_metrics["captured_at"]).total_seconds()
                        decision = self.segment_quality.decide_commit(
                            source_text=source_text,
                            translated_text=translated,
                            target_language=self.target_language,
                            route=route,
                            pending_age_s=pending_age_s,
                        )
                    retry_fallback_reason = self.translator.last_error or ""  # type: ignore[union-attr]
                    if retry_fallback_reason:
                        if fallback_reason:
                            fallback_reason = f"{fallback_reason};{retry_fallback_reason}"
                        else:
                            fallback_reason = retry_fallback_reason
                translation_time = perf_counter() - started
                if fallback_reason:
                    self.translation_fallbacks += 1
                    if self.debug_enabled:
                        logging.warning("debug_translation_fallback reason=%s", fallback_reason)
                translation_end_ts = datetime.now()
                source_metrics = dict(source_metrics)
                source_metrics["translation_start_ts"] = translation_start_ts
                source_metrics["translation_end_ts"] = translation_end_ts
                source_metrics["translation_time_s"] = translation_time
                source_metrics["source_text"] = source_text
                source_metrics["translated_text_raw"] = translated
                source_metrics["route"] = route
                source_metrics["semantic_score"] = decision.semantic_score
                source_metrics["source_confidence"] = decision.source_confidence
                source_metrics["source_incomplete"] = decision.source_incomplete
                source_metrics["mixed_script_detected"] = decision.mixed_script_detected
                source_metrics["non_target_language_detected"] = decision.non_target_language_detected
                source_metrics["translation_too_similar_to_source"] = decision.translation_too_similar_to_source
                source_metrics["semantic_drift_score"] = decision.semantic_drift_score
                source_metrics["language_guard_triggered"] = decision.language_guard_triggered
                source_metrics["dropped_reason"] = decision.dropped_reason
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
                hard_drop_reasons = {
                    "language_guard",
                    "semantic_low",
                    "commit_empty",
                    "reject_phrase",
                    "source_low_confidence",
                    "translation_too_similar",
                }
                if decision.stage == "drop" and decision.dropped_reason in hard_drop_reasons:
                    source_metrics["segment_stage"] = "drop"
                    source_metrics["route"] = "drop"
                    source_metrics["had_fallback"] = True
                    source_metrics["fallback_reason"] = source_metrics["fallback_reason"] or f"dropped:{decision.dropped_reason}"
                    self._record_drop_metrics(source_metrics)
                    self.last_api_time = float(source_metrics["transcription_time_s"]) + translation_time
                    if self.debug_enabled:
                        self._update_debug_panel(language=source_language, api_time=self.last_api_time)
                    continue

                translated_for_buffer = decision.text if decision.stage == "commit" else translated
                emitted = self._buffer_or_emit_translation(
                    translated=translated_for_buffer,
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

    def _load_reference_cues(self) -> list[SubtitleCue]:
        if self._fixture_spec is None:
            return []
        caption_path = (self._fixture_spec.reference_caption_path or "").strip()
        if not caption_path:
            return []
        return load_subtitle_cues(Path(caption_path))

    def _relative_seconds(self, value: datetime) -> float:
        return max(0.0, (value - self._session_anchor_at).total_seconds())

    def _audio_window(self, captured_at: datetime, duration_s: float) -> tuple[float, float]:
        audio_t0 = self._relative_seconds(captured_at)
        audio_t1 = audio_t0 + max(0.0, duration_s)
        return audio_t0, audio_t1

    def _reference_payload(self, audio_t0: float, audio_t1: float) -> dict[str, Any]:
        cue = match_reference_cue(self._reference_cues, audio_t0, audio_t1)
        if cue is None:
            return {
                "reference_text": "",
                "reference_t0": None,
                "reference_t1": None,
            }
        return {
            "reference_text": cue.text,
            "reference_t0": cue.start_s,
            "reference_t1": cue.end_s,
        }

    def _record_replay_asr_event(
        self,
        *,
        source_text_raw: str,
        source_text_sanitized: str,
        asr_stage: str,
        captured_at: datetime,
        duration_s: float,
        source_language: str,
        latency_s: float,
    ) -> None:
        if not self.replay_logger.enabled:
            return
        audio_t0, audio_t1 = self._audio_window(captured_at, duration_s)
        source_confidence = self.segment_quality.confidence_from_source(source_text_sanitized)
        payload = {
            "event_type": "asr",
            "fixture_id": self.replay_fixture_id,
            "source_language": source_language or "auto",
            "source_text_raw": source_text_raw,
            "source_text_sanitized": source_text_sanitized,
            "asr_stage": asr_stage,
            "audio_t0": audio_t0,
            "audio_t1": audio_t1,
            "latency_source_s": latency_s,
            "source_confidence": source_confidence,
            "source_incomplete": self.segment_quality._source_incomplete(source_text_sanitized),
            "render_t": self._relative_seconds(datetime.now()),
        }
        payload.update(self._reference_payload(audio_t0, audio_t1))
        self.replay_logger.record_event(payload)

    def _check_replay_completion(self) -> None:
        if not self.replay_audio_path or self._replay_completion_handled:
            return
        if not self.running:
            self._replay_completion_timer.stop()
            return
        if self.listener.is_running:
            return
        if not self.audio_queue.empty() or not self.text_queue.empty() or not self.stream_audio_queue.empty():
            return
        if self._pending_source_text.strip():
            self._drop_pending_source_buffer("replay_incomplete_tail")
            self.ui.clear_live_preview()
        if self._pending_render_text.strip():
            self._flush_pending_render(language=self._pending_source_language or "auto")
        if self._pending_source_text.strip() or self._pending_render_text.strip():
            return
        self._replay_completion_handled = True
        self._replay_completion_timer.stop()
        self.ui.set_status("Replay fixture completed.")
        if self.replay_auto_stop_on_complete:
            self._schedule_toggle(False)
        if self.replay_auto_exit_on_complete:
            app = QApplication.instance()
            if app is not None:
                QTimer.singleShot(350, app.quit)

    async def _enqueue_translation_item(
        self,
        *,
        chunk: AudioChunk,
        source_text: str,
        source_text_raw: str,
        source_language: str,
        transcription_time: float,
        transcription_start_ts: datetime,
        transcription_end_ts: datetime,
    ) -> None:
        item = (
            chunk,
            source_text,
            source_text_raw,
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

    def _sanitize_transcribed_text(self, source_text: str, *, source_language: str = "auto") -> str:
        cleaned = self._clean_transcription_noise((source_text or "").strip())
        if not cleaned:
            return ""
        if self._should_drop_non_english_source(cleaned, source_language=source_language):
            if self.debug_enabled:
                logging.info("debug_non_english_source_dropped lang=%s text=%r", source_language, cleaned[:120])
            return ""
        if self.filter_gibberish and self._looks_low_confidence_short_fragment(cleaned):
            if self.debug_enabled:
                logging.info("debug_short_fragment_dropped text=%r", cleaned[:120])
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

    def _should_drop_non_english_source(self, text: str, *, source_language: str) -> bool:
        if not self.strict_en_es_source_guard:
            return False
        if (self.target_language or "").strip().lower() != "spanish":
            return False
        configured_source = (self.source_language or "").strip().lower()
        if configured_source not in {"auto-detect", "auto", "english", "en"}:
            return False
        if source_language and source_language.strip().lower() not in {"auto", "unknown", "en", "english"}:
            return False
        return self._looks_non_english_source_fragment(text)

    @classmethod
    def _looks_non_english_source_fragment(cls, text: str) -> bool:
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        if not cleaned:
            return True
        lowered_full = cleaned.lower()
        if any(phrase in lowered_full for phrase in cls.GENERIC_SPANISH_NOISE_PHRASES):
            return True
        words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", cleaned)
        if len(words) < 3:
            return False
        lowered = [w.lower() for w in words]
        english_hits = sum(1 for w in lowered if w in cls.ENGLISH_FUNCTION_WORDS)
        spanish_hits = sum(1 for w in lowered if w in cls.SPANISH_FUNCTION_WORDS)
        if len(lowered) >= 5 and spanish_hits >= (english_hits + 2):
            return True
        if "¿" in cleaned or "¡" in cleaned:
            return english_hits == 0
        return False

    async def _handle_transcription_preview(self, preview_text: str) -> None:
        cleaned = self._clean_transcription_noise(preview_text)
        if not cleaned:
            return
        self._record_replay_asr_event(
            source_text_raw=preview_text,
            source_text_sanitized=cleaned,
            asr_stage="preview",
            captured_at=datetime.now(),
            duration_s=0.0,
            source_language="auto",
            latency_s=0.0,
        )
        if self.literal_complete_mode or not self.show_source_preview:
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
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(payload)
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
        self._pending_render_revision = 0
        self._source_preview_active = False
        self._last_preview_at = None
        self._last_preview_text = ""
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
            reset_context = getattr(self.translator, "reset_context", None)
            if callable(reset_context):
                reset_context()
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
        premium_ratio = metrics_snapshot.get("premium_ratio", 0.0) * 100.0
        drop_ratio = metrics_snapshot.get("drop_ratio_pct", 0.0)
        api_time = api_time if api_time is not None else self.last_api_time
        color = "#2ecc71"
        if p95_latency >= 4.0:
            color = "#e74c3c"
        elif p95_latency >= 2.5:
            color = "#f1c40f"

        del language, api_time
        debug_text = (
            f"AVG {avg_latency:.2f}s | P95 {p95_latency:.2f}s | "
            f"Drop {drop_ratio:.1f}% | Prem {premium_ratio:.0f}% | Issue {issue_rate:.1f}%"
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
    def _contains_non_latin_script(text: str) -> bool:
        return bool(re.search(r"[\u0400-\u052F\u0590-\u05FF\u0600-\u06FF\u0750-\u077F]", text or ""))

    @staticmethod
    def _token_looks_plausible(token: str) -> bool:
        normalized = re.sub(r"[^a-záéíóúüñ]+", "", (token or "").lower())
        if not normalized:
            return False
        if len(normalized) <= 2:
            return True
        if re.search(r"[bcdfghjklmnñpqrstvwxyz]{5,}", normalized):
            return False
        return bool(re.search(r"[aeiouáéíóúü]", normalized))

    @classmethod
    def _looks_low_confidence_short_fragment(cls, text: str) -> bool:
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        if not cleaned:
            return True
        if cls._contains_non_latin_script(cleaned):
            return True
        words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9'/-]+", cleaned)
        if not words:
            return True
        if len(words) > 4:
            return False
        lexical = [token for token in words if re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", token)]
        if not lexical:
            return True
        plausible_hits = sum(1 for token in lexical if cls._token_looks_plausible(token))
        if plausible_hits / len(lexical) < 0.6:
            return True
        if len(lexical) == 1:
            only = re.sub(r"[^a-záéíóúüñ]+", "", lexical[0].lower())
            if len(only) >= 9 and only not in {"translation", "incremental", "validation"}:
                return True
        return False

    @classmethod
    def _looks_gibberish(cls, text: str) -> bool:
        normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
        if cls._contains_non_latin_script(normalized):
            return True
        tokens = re.findall(r"[a-z0-9]+", normalized)
        if len(tokens) < 6:
            weird_tokens = 0
            for token in tokens:
                if len(token) >= 8 and not re.search(r"[aeiou]", token):
                    weird_tokens += 1
                    continue
                if re.search(r"[bcdfghjklmnpqrstvwxyz]{5,}", token):
                    weird_tokens += 1
            return len(tokens) >= 3 and weird_tokens >= 2

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
            r"\btranscribe spoken english accurately from noisy system audio\b",
            r"\bdo not hallucinate or invent words\b",
            r"\btranscribir ingl[eé]s hablado con precisi[oó]n desde audio de sistema ruidoso\b",
            r"\bno alucinar ni inventar palabras\b",
            r"\bpreserve names, brands, acronyms, numbers, and technical terms\b",
            r"\bpreservar nombres, marcas, acr[oó]nimos, n[uú]meros y t[eé]rminos t[eé]cnicos\b",
            r"\[(?:music|m[uú]sica)\]",
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
            self._pending_render_revision = 0
        else:
            self._pending_render_text = self._merge_fragments(self._pending_render_text, fragment)
            self._pending_metrics_data = self._merge_metrics_data(self._pending_metrics_data, metrics_data)
        merged_metrics = self._pending_metrics_data or metrics_data
        self._maybe_emit_preview_segment(
            pending_text=self._pending_render_text,
            source_language=source_language,
            api_time=api_time,
            metrics_data=merged_metrics,
        )

        should_emit = self._should_emit_pending(fragment)
        if not should_emit:
            return False
        if self.emit_min_interval_seconds > 0 and self._last_emit_at is not None and self._pending_captured_at is not None:
            now = datetime.now()
            since_last_emit = (now - self._last_emit_at).total_seconds()
            pending_age = (now - self._pending_captured_at).total_seconds()
            if (
                since_last_emit < self.emit_min_interval_seconds
                and pending_age < (self.max_pending_render_age_seconds * 1.8)
            ):
                return False

        emitted_text = self._pending_render_text
        emitted_captured_at = self._pending_captured_at or chunk_captured_at
        emitted_metrics = self._pending_metrics_data or metrics_data
        route = str(emitted_metrics.get("route") or "normal")
        if route not in {"normal", "premium"}:
            route = "normal"
        pending_age_s = max(0.0, (datetime.now() - emitted_captured_at).total_seconds())
        render_revision = self._pending_render_revision + 1
        decision = self.segment_quality.decide_commit(
            source_text=str(emitted_metrics.get("source_text") or ""),
            translated_text=emitted_text,
            target_language=self.target_language,
            route=route,  # type: ignore[arg-type]
            pending_age_s=pending_age_s,
        )
        emitted_metrics = dict(emitted_metrics)
        emitted_metrics["semantic_score"] = decision.semantic_score
        emitted_metrics["source_confidence"] = decision.source_confidence
        emitted_metrics["source_incomplete"] = decision.source_incomplete
        emitted_metrics["mixed_script_detected"] = decision.mixed_script_detected
        emitted_metrics["non_target_language_detected"] = decision.non_target_language_detected
        emitted_metrics["translation_too_similar_to_source"] = decision.translation_too_similar_to_source
        emitted_metrics["semantic_drift_score"] = decision.semantic_drift_score
        emitted_metrics["language_guard_triggered"] = decision.language_guard_triggered
        emitted_metrics["dropped_reason"] = decision.dropped_reason
        self._pending_render_text = ""
        self._pending_captured_at = None
        self._pending_metrics_data = None
        self._pending_render_revision = 0
        if decision.stage == "drop":
            dropped_metrics = dict(emitted_metrics)
            dropped_metrics["segment_stage"] = "drop"
            dropped_metrics["route"] = "drop"
            dropped_metrics["had_fallback"] = True
            dropped_metrics["fallback_reason"] = dropped_metrics.get("fallback_reason") or f"dropped:{decision.dropped_reason}"
            dropped_metrics["render_revision"] = render_revision
            self._record_drop_metrics(dropped_metrics)
            return False
        self._emit_segment(
            decision.text,
            emitted_captured_at,
            source_language,
            api_time,
            emitted_metrics,
            segment_stage="commit",
            route=decision.route,
            semantic_score=decision.semantic_score,
            language_guard_triggered=decision.language_guard_triggered,
            render_revision=render_revision,
            dropped_reason="",
        )
        return True

    def _maybe_emit_preview_segment(
        self,
        *,
        pending_text: str,
        source_language: str,
        api_time: float,
        metrics_data: dict[str, Any],
    ) -> None:
        if not self.dual_pass_enabled:
            return
        if self._pending_captured_at is None:
            return
        if self.preview_drop_backlog_threshold > 0:
            if (
                int(metrics_data.get("text_backlog", 0)) >= self.preview_drop_backlog_threshold
                or int(metrics_data.get("audio_backlog", 0)) >= self.preview_drop_backlog_threshold
            ):
                return
        now = datetime.now()
        if self._last_preview_at is not None:
            since_preview = (now - self._last_preview_at).total_seconds()
            if since_preview < min(self.preview_max_age_seconds, self.emit_min_interval_seconds):
                return
        pending_age_s = max(0.0, (now - self._pending_captured_at).total_seconds())
        route = str(metrics_data.get("route") or "normal")
        if route not in {"normal", "premium"}:
            route = "normal"
        decision = self.segment_quality.decide_preview(
            source_text=str(metrics_data.get("source_text") or ""),
            translated_text=pending_text,
            target_language=self.target_language,
            route=route,  # type: ignore[arg-type]
            pending_age_s=pending_age_s,
        )
        if decision.stage != "preview":
            return
        if decision.text == self._last_preview_text:
            return
        self._source_preview_active = True
        self._last_preview_at = now
        self._last_preview_text = decision.text
        self._pending_render_revision += 1
        self.ui.set_live_preview(decision.text)
        emit_interval_s = 0.0
        if self._last_emit_at is not None:
            emit_interval_s = max(0.0, (now - self._last_emit_at).total_seconds())
        self._record_segment_metrics(
            rendered_text=decision.text,
            captured_at=self._pending_captured_at,
            source_language=source_language,
            latency=max(0.0, (now - self._pending_captured_at).total_seconds()),
            api_time=api_time,
            metrics_data={
                **metrics_data,
                "semantic_score": decision.semantic_score,
                "source_confidence": decision.source_confidence,
                "source_incomplete": decision.source_incomplete,
                "mixed_script_detected": decision.mixed_script_detected,
                "non_target_language_detected": decision.non_target_language_detected,
                "translation_too_similar_to_source": decision.translation_too_similar_to_source,
                "semantic_drift_score": decision.semantic_drift_score,
                "language_guard_triggered": decision.language_guard_triggered,
            },
            segment_stage="preview",
            route=decision.route,
            semantic_score=decision.semantic_score,
            language_guard_triggered=decision.language_guard_triggered,
            render_revision=self._pending_render_revision,
            emit_interval_s=emit_interval_s,
            dropped_reason="",
        )

    def _emit_segment(
        self,
        translated_text: str,
        captured_at: datetime,
        source_language: str,
        api_time: float,
        metrics_data: Optional[dict[str, Any]] = None,
        *,
        segment_stage: str = "commit",
        route: TranslationRoute = "normal",
        semantic_score: float = 0.0,
        language_guard_triggered: bool = False,
        render_revision: int = 0,
        dropped_reason: str = "",
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
        self._last_preview_text = ""
        self.ui.clear_live_preview()

        timestamp = datetime.now()
        emit_interval_s = 0.0
        if self._last_emit_at is not None:
            emit_interval_s = max(0.0, (timestamp - self._last_emit_at).total_seconds())
        self._last_emit_at = timestamp
        rendered = f"[{self._format_timestamp(timestamp)}] {cleaned}"
        if self._is_duplicate_segment(rendered):
            return
        if self.log_rendered_segments:
            logging.info("segment_out source_lang=%s text=%s", source_language, cleaned)
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
            segment_stage=segment_stage,
            route=route,
            semantic_score=semantic_score,
            language_guard_triggered=language_guard_triggered,
            render_revision=render_revision,
            emit_interval_s=emit_interval_s,
            dropped_reason=dropped_reason,
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
        route = str(pending_metrics.get("route") or "normal")
        if route not in {"normal", "premium"}:
            route = "normal"
        render_revision = self._pending_render_revision + 1
        decision = self.segment_quality.decide_commit(
            source_text=str(pending_metrics.get("source_text") or ""),
            translated_text=pending,
            target_language=self.target_language,
            route=route,  # type: ignore[arg-type]
            pending_age_s=max(0.0, (datetime.now() - captured_at).total_seconds()),
        )
        pending_metrics = dict(pending_metrics)
        pending_metrics["semantic_score"] = decision.semantic_score
        pending_metrics["source_confidence"] = decision.source_confidence
        pending_metrics["source_incomplete"] = decision.source_incomplete
        pending_metrics["mixed_script_detected"] = decision.mixed_script_detected
        pending_metrics["non_target_language_detected"] = decision.non_target_language_detected
        pending_metrics["translation_too_similar_to_source"] = decision.translation_too_similar_to_source
        pending_metrics["semantic_drift_score"] = decision.semantic_drift_score
        pending_metrics["language_guard_triggered"] = decision.language_guard_triggered
        pending_metrics["dropped_reason"] = decision.dropped_reason
        self._pending_render_text = ""
        self._pending_captured_at = None
        self._pending_metrics_data = None
        self._pending_render_revision = 0
        if decision.stage == "drop":
            dropped_metrics = dict(pending_metrics)
            dropped_metrics["segment_stage"] = "drop"
            dropped_metrics["route"] = "drop"
            dropped_metrics["had_fallback"] = True
            dropped_metrics["fallback_reason"] = dropped_metrics.get("fallback_reason") or f"dropped:{decision.dropped_reason}"
            dropped_metrics["render_revision"] = render_revision
            self._record_drop_metrics(dropped_metrics)
            return
        self._emit_segment(
            decision.text,
            captured_at,
            language,
            self.last_api_time,
            pending_metrics,
            segment_stage="commit",
            route=decision.route,
            semantic_score=decision.semantic_score,
            language_guard_triggered=decision.language_guard_triggered,
            render_revision=render_revision,
            dropped_reason="",
        )

    def _maybe_show_source_preview(self, source_text: str) -> None:
        if self.literal_complete_mode or not self.show_source_preview:
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
        raw_fragment = self._normalize_fragment(str(metrics_data.get("source_text_raw") or source_text))
        if not self._pending_source_text:
            self._pending_source_text = fragment
            self._pending_source_raw_text = raw_fragment
            self._pending_source_captured_at = chunk_captured_at
            self._pending_source_language = source_language or "auto"
            self._pending_source_metrics_data = dict(metrics_data)
            self._pending_source_fragment_count = 1
        else:
            self._pending_source_text = self._merge_fragments(self._pending_source_text, fragment)
            self._pending_source_raw_text = self._merge_fragments(self._pending_source_raw_text, raw_fragment)
            self._pending_source_language = source_language or self._pending_source_language or "auto"
            self._pending_source_metrics_data = self._merge_metrics_data(self._pending_source_metrics_data, metrics_data)
            self._pending_source_fragment_count += 1
        self._maybe_show_source_preview(self._pending_source_text)

    def _consume_pending_source_buffer(self) -> Optional[tuple[str, str, str, dict[str, Any]]]:
        pending = self._pending_source_text.strip()
        if not pending:
            return None
        raw_pending = self._pending_source_raw_text.strip() or pending
        language = self._pending_source_language or "auto"
        metrics_data = dict(self._pending_source_metrics_data or {})
        self._reset_pending_source_buffer()
        return pending, raw_pending, language, metrics_data

    def _drop_pending_source_buffer(self, reason: str) -> None:
        pending = self._pending_source_text.strip()
        if not pending:
            return
        metrics_data = dict(self._pending_source_metrics_data or {})
        metrics_data["source_text_raw"] = self._pending_source_raw_text.strip() or pending
        metrics_data["source_text_sanitized"] = pending
        metrics_data["source_text"] = pending
        metrics_data["segment_stage"] = "drop"
        metrics_data["route"] = "drop"
        metrics_data["semantic_score"] = float(metrics_data.get("semantic_score", 0.0) or 0.0)
        metrics_data["language_guard_triggered"] = bool(metrics_data.get("language_guard_triggered", False))
        metrics_data["dropped_reason"] = reason
        metrics_data["had_fallback"] = True
        metrics_data["fallback_reason"] = metrics_data.get("fallback_reason") or f"dropped:{reason}"
        metrics_data["render_revision"] = self._pending_render_revision + 1
        self._record_drop_metrics(metrics_data)
        self._reset_pending_source_buffer()

    def _reset_pending_source_buffer(self) -> None:
        self._pending_source_text = ""
        self._pending_source_raw_text = ""
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
        has_terminal_punctuation = re.search(r"[.!?]\s*$", pending) is not None
        if (
            self.strict_en_es_source_guard
            and (self.target_language or "").strip().lower() == "spanish"
            and not has_terminal_punctuation
            and not incomplete_tail
            and word_count < max(self.source_strict_min_words, self.SOURCE_TRANSLATION_MIN_WORDS)
            and (age_s is None or age_s < self.source_strict_max_wait_seconds)
        ):
            return False
        if self.chunks_processed == 0 and age_s is not None and not incomplete_tail:
            if word_count >= self.MIN_WORDS_ON_AGE_FLUSH and age_s >= self.SOURCE_TRANSLATION_FIRST_AGE_SECONDS:
                return True
        if has_terminal_punctuation and word_count >= self.min_emit_words:
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
        merged["audio_duration_s"] = float(previous.get("audio_duration_s", 0.0) or 0.0) + float(
            incoming.get("audio_duration_s", 0.0) or 0.0
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
        merged["fixture_id"] = incoming.get("fixture_id") or previous.get("fixture_id", "")
        merged["source_text_raw"] = incoming.get("source_text_raw") or previous.get("source_text_raw", "")
        merged["source_text_sanitized"] = incoming.get("source_text_sanitized") or previous.get("source_text_sanitized", "")
        merged["source_text"] = incoming.get("source_text") or previous.get("source_text", "")
        merged["source_confidence"] = max(
            float(previous.get("source_confidence", 0.0) or 0.0),
            float(incoming.get("source_confidence", 0.0) or 0.0),
        )
        merged["source_incomplete"] = bool(previous.get("source_incomplete", False) or incoming.get("source_incomplete", False))
        merged["mixed_script_detected"] = bool(
            previous.get("mixed_script_detected", False) or incoming.get("mixed_script_detected", False)
        )
        merged["non_target_language_detected"] = bool(
            previous.get("non_target_language_detected", False) or incoming.get("non_target_language_detected", False)
        )
        merged["translation_too_similar_to_source"] = bool(
            previous.get("translation_too_similar_to_source", False)
            or incoming.get("translation_too_similar_to_source", False)
        )
        merged["route"] = (
            "premium"
            if (previous.get("route") == "premium" or incoming.get("route") == "premium")
            else incoming.get("route") or previous.get("route", "normal")
        )
        merged["semantic_score"] = max(
            float(previous.get("semantic_score", 0.0) or 0.0),
            float(incoming.get("semantic_score", 0.0) or 0.0),
        )
        merged["language_guard_triggered"] = bool(
            previous.get("language_guard_triggered", False) or incoming.get("language_guard_triggered", False)
        )
        merged["semantic_drift_score"] = max(
            float(previous.get("semantic_drift_score", 0.0) or 0.0),
            float(incoming.get("semantic_drift_score", 0.0) or 0.0),
        )
        merged["dropped_reason"] = incoming.get("dropped_reason") or previous.get("dropped_reason", "")
        return merged

    def _record_segment_metrics(
        self,
        rendered_text: str,
        captured_at: datetime,
        source_language: str,
        latency: float,
        api_time: float,
        metrics_data: Optional[dict[str, Any]],
        *,
        segment_stage: str = "commit",
        route: TranslationRoute = "normal",
        semantic_score: float = 0.0,
        language_guard_triggered: bool = False,
        render_revision: int = 0,
        emit_interval_s: float = 0.0,
        dropped_reason: str = "",
    ) -> None:
        if (
            not self.metrics_reporter.enabled
            and not self.replay_logger.enabled
        ):
            return
        skip_metrics_segment = bool(
            self.metrics_reporter.enabled
            and segment_stage == "commit"
            and len(rendered_text.strip()) < self.metrics_min_text_len
        )
        data = dict(metrics_data or {})
        data.setdefault("captured_at", captured_at)
        data.setdefault("audio_duration_s", 0.0)
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
        data.setdefault("source_text", "")
        data.setdefault("source_text_raw", data.get("source_text", ""))
        data.setdefault("source_text_sanitized", data.get("source_text", ""))
        data.setdefault("source_confidence", 0.0)
        data.setdefault("source_incomplete", False)
        data.setdefault("mixed_script_detected", False)
        data.setdefault("non_target_language_detected", False)
        data.setdefault("translation_too_similar_to_source", False)
        data.setdefault("semantic_drift_score", max(0.0, 1.0 - float(data.get("semantic_score", semantic_score) or 0.0)))
        data.setdefault("fixture_id", self.replay_fixture_id)
        data.setdefault("route", route)
        data.setdefault("semantic_score", semantic_score)
        data.setdefault("language_guard_triggered", language_guard_triggered)
        data.setdefault("dropped_reason", dropped_reason)
        data.setdefault("test_id", self.benchmark_test_id or "N/D")
        audio_t0, audio_t1 = self._audio_window(captured_at, float(data.get("audio_duration_s", 0.0) or 0.0))
        reference_payload = self._reference_payload(audio_t0, audio_t1)
        render_t = self._relative_seconds(datetime.now())
        payload = {
            "event_type": "segment",
            "recorded_at": datetime.now().isoformat(timespec="milliseconds"),
            "fixture_id": str(data.get("fixture_id") or self.replay_fixture_id),
            "test_id": str(data.get("test_id") or "N/D"),
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
            "segment_stage": segment_stage,
            "route": str(data["route"] or route),
            "semantic_score": float(data["semantic_score"]),
            "language_guard_triggered": bool(data["language_guard_triggered"]),
            "emit_interval_s": float(emit_interval_s),
            "dropped_reason": str(data["dropped_reason"] or dropped_reason),
            "rendered_text": rendered_text,
            "source_text_raw": str(data.get("source_text_raw") or data.get("source_text") or ""),
            "source_text_sanitized": str(data.get("source_text_sanitized") or data.get("source_text") or ""),
            "source_text": str(data.get("source_text") or ""),
            "source_confidence": float(data.get("source_confidence", 0.0) or 0.0),
            "source_incomplete": bool(data.get("source_incomplete", False)),
            "mixed_script_detected": bool(data.get("mixed_script_detected", False)),
            "non_target_language_detected": bool(data.get("non_target_language_detected", False)),
            "translation_too_similar_to_source": bool(data.get("translation_too_similar_to_source", False)),
            "semantic_drift_score": float(data.get("semantic_drift_score", 0.0) or 0.0),
            "asr_stage": "stable",
            "translation_stage": segment_stage,
            "render_revision": int(data.get("render_revision", render_revision) or render_revision),
            "audio_t0": audio_t0,
            "audio_t1": audio_t1,
            "render_t": render_t,
            "reference_text": str(reference_payload.get("reference_text") or ""),
            "reference_t0": reference_payload.get("reference_t0"),
            "reference_t1": reference_payload.get("reference_t1"),
        }
        if self.metrics_reporter.enabled and not skip_metrics_segment:
            self.metrics_reporter.record_segment(payload)
        if self.replay_logger.enabled:
            self.replay_logger.record_event(dict(payload))

    def _record_drop_metrics(self, metrics_data: dict[str, Any]) -> None:
        captured_at = metrics_data.get("captured_at") or datetime.now()
        if not isinstance(captured_at, datetime):
            captured_at = datetime.now()
        source_language = str(metrics_data.get("source_language") or "auto")
        translation_end = metrics_data.get("translation_end_ts")
        if isinstance(translation_end, datetime):
            latency = max(0.0, (translation_end - captured_at).total_seconds())
        else:
            latency = max(0.0, (datetime.now() - captured_at).total_seconds())
        self._record_segment_metrics(
            rendered_text="",
            captured_at=captured_at,
            source_language=source_language,
            latency=latency,
            api_time=float(metrics_data.get("transcription_time_s", 0.0)) + float(metrics_data.get("translation_time_s", 0.0)),
            metrics_data=metrics_data,
            segment_stage="drop",
            route="drop",
            semantic_score=float(metrics_data.get("semantic_score", 0.0) or 0.0),
            language_guard_triggered=bool(metrics_data.get("language_guard_triggered", False)),
            emit_interval_s=0.0,
            dropped_reason=str(metrics_data.get("dropped_reason") or "unknown"),
        )

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
        target_words = max(self.merge_min_words, self.min_emit_words, self.commit_min_words)
        if self._source_preview_active and word_count >= self.MIN_WORDS_ON_AGE_FLUSH:
            return True
        if self._pending_captured_at:
            age_s = (datetime.now() - self._pending_captured_at).total_seconds()
            # Hard upper bound for on-screen delay while listening.
            hard_age = min(self.max_pending_render_age_seconds, self.commit_max_age_seconds)
            if age_s >= hard_age:
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
        if (self.text_queue.qsize() > 0 or self._current_audio_backlog() > 0) and word_count >= max(
            self.min_emit_words,
            self.commit_min_words - 1,
        ):
            return True
        if word_count >= self.merge_max_words:
            return True
        if sentence_end:
            return word_count >= max(self.min_emit_words, self.commit_min_words - 1)
        if re.search(r"[,:;]\s*$", latest_fragment):
            return False
        return word_count >= target_words and len(pending) >= self.emit_min_chars

    def _format_timestamp(self, timestamp: datetime) -> str:
        return timestamp.strftime("%M:%S" if self.short_timestamps else "%H:%M:%S")


def main() -> None:
    load_dotenv()
    log_level_name = (os.getenv("LOG_LEVEL", "INFO") or "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    live_log_path = Path(os.getenv("LIVE_RUN_LOG_PATH", "./reports/live_run.log"))
    live_log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(live_log_path, mode="a", encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )
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
