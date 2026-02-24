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

    async def transcribe(self, wav_bytes: bytes) -> TranscriptionResult:
        last_error: Optional[Exception] = None
        while self._active_model_index < len(self._models):
            model_name = self._models[self._active_model_index]
            attempt = 0
            unsupported_model = False
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
                        model=model_name,
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
                    if exc.status_code in (400, 404):
                        unsupported_model = True
                        break
                    await asyncio.sleep(0.4 * attempt)
                except Exception as exc:  # noqa: BLE001 - service boundary
                    last_error = exc
                    await asyncio.sleep(0.4 * attempt)

            # Promote to fallback model if primary is unavailable or exhausted retries.
            self._active_model_index += 1
            if not unsupported_model and self._active_model_index >= len(self._models):
                break

        raise RuntimeError(f"Transcription failed with all configured models: {last_error}") from last_error

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
