from __future__ import annotations

import asyncio
import io
import os
from dataclasses import dataclass
from time import perf_counter
from typing import Optional

from openai import APIStatusError, AsyncOpenAI


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

    async def transcribe(self, wav_bytes: bytes) -> TranscriptionResult:
        attempt = 0
        last_error: Optional[Exception] = None
        while attempt < self._max_retries:
            attempt += 1
            started = perf_counter()
            try:
                audio_file = io.BytesIO(wav_bytes)
                audio_file.name = "chunk.wav"
                response = await self._client.audio.transcriptions.create(
                    model=self._model,
                    file=audio_file,
                    response_format="verbose_json",
                    temperature=0,
                    prompt=self._prompt_context[-220:] if self._prompt_context else None,
                )

                text = self._read_value(response, "text").strip()
                language = self._read_value(response, "language").strip().lower() or "unknown"
                if text:
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

    @staticmethod
    def _read_value(response, key: str) -> str:
        if hasattr(response, key):
            value = getattr(response, key)
            return "" if value is None else str(value)
        if isinstance(response, dict):
            value = response.get(key)
            return "" if value is None else str(value)
        return ""
