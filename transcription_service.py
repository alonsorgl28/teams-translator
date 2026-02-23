from __future__ import annotations

import asyncio
import io
import os
from dataclasses import dataclass
from time import perf_counter
from typing import Optional

from openai import APIStatusError, AsyncOpenAI

from config_utils import read_bool_env, read_int_env


@dataclass
class TranscriptionResult:
    text: str
    language: str
    latency_s: float


class WhisperTranscriptionService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "whisper-1",
        max_retries: int = 3,
    ) -> None:
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is required for transcription.")
        self._client = AsyncOpenAI(api_key=key)
        self._model = model
        self._max_retries = max_retries
        self._prompt_context = ""
        language_hint = (os.getenv("TRANSCRIPTION_LANGUAGE_HINT") or "").strip().lower()
        self._language_hint = None if language_hint in {"", "auto"} else language_hint
        self._context_enabled = read_bool_env("TRANSCRIPTION_CONTEXT_ENABLED", False)
        self._context_max_chars = read_int_env("TRANSCRIPTION_CONTEXT_MAX_CHARS", 220)
        self._base_prompt = (os.getenv("TRANSCRIPTION_BASE_PROMPT") or "").strip()

    async def transcribe(self, wav_bytes: bytes) -> TranscriptionResult:
        attempt = 0
        last_error: Optional[Exception] = None
        while attempt < self._max_retries:
            attempt += 1
            started = perf_counter()
            try:
                audio_file = io.BytesIO(wav_bytes)
                audio_file.name = "chunk.wav"
                rolling_prompt = (
                    self._prompt_context[-self._context_max_chars :]
                    if self._context_enabled and self._prompt_context
                    else ""
                )
                combined_prompt = " ".join(part for part in (self._base_prompt, rolling_prompt) if part).strip()
                response = await self._client.audio.transcriptions.create(
                    model=self._model,
                    file=audio_file,
                    response_format="verbose_json",
                    temperature=0,
                    prompt=combined_prompt or None,
                    language=self._language_hint,
                )

                text = self._read_value(response, "text").strip()
                language = self._read_value(response, "language").strip().lower() or "unknown"
                if text and self._context_enabled:
                    # Keep a short rolling context to improve short-chunk continuity.
                    self._prompt_context = f"{self._prompt_context} {text}".strip()[-500:]
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
                await asyncio.sleep(0.4 * attempt)
            except Exception as exc:  # noqa: BLE001 - service boundary
                last_error = exc
                await asyncio.sleep(0.4 * attempt)

        raise RuntimeError(f"Transcription failed after retries: {last_error}") from last_error

    def reset_context(self) -> None:
        self._prompt_context = ""

    @staticmethod
    def _read_value(response, key: str) -> str:
        if hasattr(response, key):
            value = getattr(response, key)
            return "" if value is None else str(value)
        if isinstance(response, dict):
            value = response.get(key)
            return "" if value is None else str(value)
        return ""
