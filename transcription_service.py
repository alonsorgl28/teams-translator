from __future__ import annotations

import asyncio
import base64
import io
import os
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Awaitable, Callable, Optional

import numpy as np
from openai import APIStatusError, AsyncOpenAI

from config_utils import read_bool_env, read_float_env, read_int_env


@dataclass
class TranscriptionResult:
    text: str
    language: str
    latency_s: float


@dataclass
class RealtimeTranscriptionEvent:
    kind: str
    item_id: str
    text: str
    language: str
    captured_at: datetime
    latency_s: float = 0.0
    error: str = ""


class WhisperTranscriptionService:
    _JSON_ONLY_MODELS = {
        "gpt-4o-transcribe",
        "gpt-4o-mini-transcribe",
        "gpt-4o-mini-transcribe-2025-12-15",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini-transcribe",
        max_retries: int = 3,
    ) -> None:
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is required for transcription.")
        self._client = AsyncOpenAI(api_key=key)
        primary_model = os.getenv("TRANSCRIPTION_MODEL", model).strip() or model
        fallback_model = os.getenv("TRANSCRIPTION_FALLBACK_MODEL", "whisper-1").strip() or "whisper-1"
        self._models = [primary_model]
        if fallback_model and fallback_model not in self._models:
            self._models.append(fallback_model)
        self._active_model_index = 0
        self._max_retries = max_retries
        self._prompt_context = ""
        language_hint = (os.getenv("TRANSCRIPTION_LANGUAGE_HINT") or "").strip().lower()
        self._language_hint = None if language_hint in {"", "auto"} else language_hint
        self._context_enabled = read_bool_env("TRANSCRIPTION_CONTEXT_ENABLED", False)
        self._context_max_chars = read_int_env("TRANSCRIPTION_CONTEXT_MAX_CHARS", 220)
        self._base_prompt = (os.getenv("TRANSCRIPTION_BASE_PROMPT") or "").strip()

    async def transcribe(
        self,
        wav_bytes: bytes,
        preview_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> TranscriptionResult:
        last_error: Optional[Exception] = None
        for model_index in range(self._active_model_index, len(self._models)):
            model_name = self._models[model_index]
            attempt = 0
            while attempt < self._max_retries:
                attempt += 1
                started = perf_counter()
                try:
                    audio_file = io.BytesIO(wav_bytes)
                    audio_file.name = "chunk.wav"
                    response = None
                    rolling_prompt = (
                        self._prompt_context[-self._context_max_chars :]
                        if self._context_enabled and self._prompt_context
                        else ""
                    )
                    combined_prompt = " ".join(part for part in (self._base_prompt, rolling_prompt) if part).strip()
                    if model_name != "whisper-1":
                        text = await self._stream_transcription_text(
                            model_name=model_name,
                            audio_file=audio_file,
                            prompt=combined_prompt or None,
                            preview_callback=preview_callback,
                        )
                    else:
                        response = await self._client.audio.transcriptions.create(
                            **self._build_request_kwargs(
                                model_name=model_name,
                                audio_file=audio_file,
                                prompt=combined_prompt or None,
                            )
                        )
                        text = self._read_value(response, "text").strip()
                    language = self._read_value(response, "language").strip().lower() or (self._language_hint or "unknown")
                    if text and self._context_enabled:
                        self._prompt_context = f"{self._prompt_context} {text}".strip()[-500:]
                    if model_index != self._active_model_index:
                        self._active_model_index = model_index
                    return TranscriptionResult(
                        text=text,
                        language=language,
                        latency_s=perf_counter() - started,
                    )
                except APIStatusError as exc:
                    last_error = exc
                    if exc.status_code in (401, 403):
                        raise RuntimeError(
                            "Authentication failed (401/403). Verify OPENAI_API_KEY in .env."
                        ) from exc
                    if exc.status_code in (400, 404):
                        break
                    await asyncio.sleep(0.4 * attempt)
                except Exception as exc:  # noqa: BLE001 - service boundary
                    last_error = exc
                    await asyncio.sleep(0.4 * attempt)

        raise RuntimeError(f"Transcription failed with all configured models: {last_error}") from last_error

    def reset_context(self) -> None:
        self._prompt_context = ""

    def _build_request_kwargs(self, *, model_name: str, audio_file: io.BytesIO, prompt: Optional[str]) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "model": model_name,
            "file": audio_file,
            "prompt": prompt,
            "language": self._language_hint,
        }
        if model_name in self._JSON_ONLY_MODELS:
            # gpt-4o transcribe models reject verbose_json on this endpoint.
            kwargs["response_format"] = "json"
            return kwargs
        kwargs["response_format"] = "verbose_json"
        kwargs["temperature"] = 0
        return kwargs

    async def _stream_transcription_text(
        self,
        *,
        model_name: str,
        audio_file: io.BytesIO,
        prompt: Optional[str],
        preview_callback: Optional[Callable[[str], Awaitable[None]]],
    ) -> str:
        stream = await self._client.audio.transcriptions.create(
            **self._build_request_kwargs(
                model_name=model_name,
                audio_file=audio_file,
                prompt=prompt,
            ),
            stream=True,
        )
        if not hasattr(stream, "__aiter__"):
            return self._read_value(stream, "text").strip()
        preview_text = ""
        final_text = ""
        async for event in stream:
            event_type = getattr(event, "type", "")
            if event_type == "transcript.text.delta":
                delta = getattr(event, "delta", "") or ""
                if not delta:
                    continue
                preview_text = self._merge_preview_text(preview_text, delta)
                if preview_callback is not None and preview_text.strip():
                    await preview_callback(preview_text)
                continue
            if event_type == "transcript.text.done":
                final_text = (getattr(event, "text", "") or "").strip()
        return final_text or preview_text.strip()

    @staticmethod
    def _merge_preview_text(current: str, delta: str) -> str:
        current = " ".join((current or "").split())
        delta = " ".join((delta or "").split())
        if not current:
            return delta
        if not delta:
            return current
        if delta in current:
            return current
        return f"{current}{delta}" if current.endswith(("-", "/")) else f"{current} {delta}".strip()

    @staticmethod
    def _read_value(response, key: str) -> str:
        if hasattr(response, key):
            value = getattr(response, key)
            return "" if value is None else str(value)
        if isinstance(response, dict):
            value = response.get(key)
            return "" if value is None else str(value)
        return ""


class RealtimeTranscriptionService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini-transcribe",
    ) -> None:
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is required for realtime transcription.")
        self._client = AsyncOpenAI(api_key=key)
        primary_session_model = os.getenv("REALTIME_SESSION_MODEL", "gpt-realtime-mini").strip() or "gpt-realtime-mini"
        fallback_session_model = os.getenv("REALTIME_SESSION_FALLBACK_MODEL", "gpt-realtime").strip() or "gpt-realtime"
        self._session_models = [primary_session_model]
        if fallback_session_model and fallback_session_model not in self._session_models:
            self._session_models.append(fallback_session_model)
        self._active_session_model_index = 0
        self._session_model = primary_session_model
        primary_model = os.getenv("TRANSCRIPTION_MODEL", model).strip() or model
        fallback_model = os.getenv("TRANSCRIPTION_FALLBACK_MODEL", "whisper-1").strip() or "whisper-1"
        self._models = [primary_model]
        if fallback_model and fallback_model not in self._models:
            self._models.append(fallback_model)
        self._active_model_index = 0
        self._model = primary_model
        language_hint = (os.getenv("TRANSCRIPTION_LANGUAGE_HINT") or "").strip().lower()
        self._language_hint = None if language_hint in {"", "auto"} else language_hint
        self._base_prompt = (os.getenv("TRANSCRIPTION_BASE_PROMPT") or "").strip()
        self._vad_threshold = read_float_env("REALTIME_VAD_THRESHOLD", 0.45)
        self._vad_prefix_padding_ms = read_int_env("REALTIME_VAD_PREFIX_MS", 220)
        self._vad_silence_duration_ms = read_int_env("REALTIME_VAD_SILENCE_MS", 220)
        self._event_queue: asyncio.Queue[RealtimeTranscriptionEvent] = asyncio.Queue(
            maxsize=read_int_env("REALTIME_EVENT_QUEUE_MAXSIZE", 128)
        )
        self._connection = None
        self._receiver_task: Optional[asyncio.Task[None]] = None
        self._running = False
        self._preview_text_by_item: dict[str, str] = {}
        self._item_started_at: dict[str, datetime] = {}
        self._last_audio_captured_at: Optional[datetime] = None
        self.last_error: Optional[str] = None

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        last_error: Optional[Exception] = None
        for session_model_index in range(self._active_session_model_index, len(self._session_models)):
            session_model_name = self._session_models[session_model_index]
            for model_index in range(self._active_model_index, len(self._models)):
                model_name = self._models[model_index]
                connection = None
                try:
                    connection = await self._client.realtime.connect(model=session_model_name).enter()
                    transcription_config = {"model": model_name}
                    if self._language_hint:
                        transcription_config["language"] = self._language_hint
                    if self._base_prompt:
                        transcription_config["prompt"] = self._base_prompt
                    await connection.session.update(
                        session={
                            "type": "transcription",
                            "audio": {
                                "input": {
                                    "format": {"type": "audio/pcm", "rate": 24000},
                                    "transcription": transcription_config,
                                    "turn_detection": {
                                        "type": "server_vad",
                                        "prefix_padding_ms": self._vad_prefix_padding_ms,
                                        "silence_duration_ms": self._vad_silence_duration_ms,
                                        "threshold": self._vad_threshold,
                                    },
                                }
                            },
                        }
                    )
                    self._connection = connection
                    self._active_session_model_index = session_model_index
                    self._active_model_index = model_index
                    self._session_model = session_model_name
                    self._model = model_name
                    self._running = True
                    self._receiver_task = asyncio.create_task(
                        self._receive_events(),
                        name="realtime-transcription-recv",
                    )
                    return
                except Exception as exc:  # noqa: BLE001 - realtime startup boundary
                    last_error = exc
                    if connection is not None:
                        with suppress(Exception):
                            await connection.close()

        raise RuntimeError(f"Realtime transcription failed with all configured models: {last_error}") from last_error

    async def stop(self) -> None:
        self._running = False
        if self._receiver_task is not None:
            self._receiver_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._receiver_task
            self._receiver_task = None
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
        self.reset_context()
        while not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def reset_context(self) -> None:
        self._preview_text_by_item.clear()
        self._item_started_at.clear()
        self._last_audio_captured_at = None
        self.last_error = None

    async def append_audio(self, samples: np.ndarray, sample_rate: int, captured_at: datetime) -> None:
        if not self._running or self._connection is None:
            return
        self._last_audio_captured_at = captured_at
        pcm16_bytes = self._to_pcm16_24khz(samples, sample_rate)
        await self._connection.input_audio_buffer.append(audio=base64.b64encode(pcm16_bytes).decode("ascii"))

    async def get_event(self) -> RealtimeTranscriptionEvent:
        return await self._event_queue.get()

    async def _receive_events(self) -> None:
        assert self._connection is not None
        try:
            async for event in self._connection:
                event_type = getattr(event, "type", "")
                if event_type == "input_audio_buffer.speech_started":
                    self._item_started_at.setdefault(
                        event.item_id,
                        self._last_audio_captured_at or datetime.now(),
                    )
                    continue
                if event_type == "input_audio_buffer.committed":
                    self._item_started_at.setdefault(
                        event.item_id,
                        self._last_audio_captured_at or datetime.now(),
                    )
                    continue
                if event_type == "conversation.item.input_audio_transcription.delta":
                    await self._handle_delta_event(event)
                    continue
                if event_type == "conversation.item.input_audio_transcription.completed":
                    await self._handle_completed_event(event)
                    continue
                if event_type == "conversation.item.input_audio_transcription.failed":
                    await self._handle_failed_event(event)
                    continue
                if event_type == "error":
                    message = getattr(getattr(event, "error", None), "message", None) or "Unknown realtime transcription error"
                    self.last_error = str(message)
                    await self._enqueue_event(
                        RealtimeTranscriptionEvent(
                            kind="error",
                            item_id="",
                            text="",
                            language=self._language_hint or "auto",
                            captured_at=self._last_audio_captured_at or datetime.now(),
                            error=self.last_error,
                        )
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - realtime boundary
            self.last_error = str(exc)
            await self._enqueue_event(
                RealtimeTranscriptionEvent(
                    kind="error",
                    item_id="",
                    text="",
                    language=self._language_hint or "auto",
                    captured_at=self._last_audio_captured_at or datetime.now(),
                    error=self.last_error,
                )
            )

    async def _handle_delta_event(self, event) -> None:
        item_id = getattr(event, "item_id", "") or ""
        delta = (getattr(event, "delta", None) or "").strip()
        if not item_id or not delta:
            return
        current = self._preview_text_by_item.get(item_id, "")
        merged = self._merge_preview_text(current, delta)
        self._preview_text_by_item[item_id] = merged
        await self._enqueue_event(
            RealtimeTranscriptionEvent(
                kind="preview",
                item_id=item_id,
                text=merged,
                language=self._language_hint or "auto",
                captured_at=self._item_started_at.get(item_id, self._last_audio_captured_at or datetime.now()),
            )
        )

    async def _handle_completed_event(self, event) -> None:
        item_id = getattr(event, "item_id", "") or ""
        transcript = (getattr(event, "transcript", None) or "").strip()
        if not item_id or not transcript:
            return
        captured_at = self._item_started_at.pop(item_id, self._last_audio_captured_at or datetime.now())
        self._preview_text_by_item.pop(item_id, None)
        await self._enqueue_event(
            RealtimeTranscriptionEvent(
                kind="final",
                item_id=item_id,
                text=transcript,
                language=self._language_hint or "auto",
                captured_at=captured_at,
                latency_s=(datetime.now() - captured_at).total_seconds(),
            )
        )

    async def _handle_failed_event(self, event) -> None:
        item_id = getattr(event, "item_id", "") or ""
        error = getattr(event, "error", None)
        message = getattr(error, "message", None) or "Realtime transcription failed"
        self._preview_text_by_item.pop(item_id, None)
        captured_at = self._item_started_at.pop(item_id, self._last_audio_captured_at or datetime.now())
        self.last_error = str(message)
        await self._enqueue_event(
            RealtimeTranscriptionEvent(
                kind="error",
                item_id=item_id,
                text="",
                language=self._language_hint or "auto",
                captured_at=captured_at,
                error=self.last_error,
            )
        )

    async def _enqueue_event(self, event: RealtimeTranscriptionEvent) -> None:
        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                self._event_queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            self._event_queue.put_nowait(event)

    @staticmethod
    def _merge_preview_text(current: str, delta: str) -> str:
        current = " ".join((current or "").split())
        delta = " ".join((delta or "").split())
        if not current:
            return delta
        if not delta:
            return current
        if delta in current:
            return current
        return f"{current}{delta}" if current.endswith(("-", "/")) else f"{current} {delta}".strip()

    @staticmethod
    def _to_pcm16_24khz(samples: np.ndarray, sample_rate: int) -> bytes:
        mono = np.asarray(samples, dtype=np.float32).reshape(-1)
        if sample_rate != 24000:
            target_len = max(1, int(round(mono.shape[0] * 24000 / sample_rate)))
            src_x = np.linspace(0.0, 1.0, num=mono.shape[0], endpoint=False)
            dst_x = np.linspace(0.0, 1.0, num=target_len, endpoint=False)
            mono = np.interp(dst_x, src_x, mono).astype(np.float32)
        clamped = np.clip(mono, -1.0, 1.0)
        return (clamped * 32767).astype(np.int16).tobytes()
