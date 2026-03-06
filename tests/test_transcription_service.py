from __future__ import annotations

import asyncio
import io
import os
import unittest
import wave
from unittest.mock import AsyncMock

import httpx
import numpy as np
from openai import APIStatusError

from transcription_service import RealtimeTranscriptionService, WhisperTranscriptionService


class _FakeResponse:
    def __init__(self, text: str, language: str = "en") -> None:
        self.text = text
        self.language = language


def _api_status_error(status_code: int, message: str) -> APIStatusError:
    request = httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions")
    response = httpx.Response(status_code=status_code, request=request)
    return APIStatusError(message, response=response, body={"error": {"message": message}})


def _dummy_wav_bytes() -> bytes:
    samples = (np.sin(np.linspace(0, np.pi * 2, 800)) * 0.1).astype(np.float32)
    int16_samples = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(int16_samples.tobytes())
    return buf.getvalue()


class TranscriptionFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_key = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "test-key"

    def tearDown(self) -> None:
        if self._orig_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = self._orig_key

    def test_fallback_model_is_promoted_after_primary_400(self) -> None:
        service = WhisperTranscriptionService(api_key="test-key")
        service._models = ["primary-bad", "fallback-good"]
        service._active_model_index = 0
        service._client.audio.transcriptions.create = AsyncMock(
            side_effect=[
                _api_status_error(400, "primary invalid request"),
                _FakeResponse("hello world", "en"),
            ]
        )

        result = asyncio.run(service.transcribe(_dummy_wav_bytes()))

        self.assertEqual(result.text, "hello world")
        self.assertEqual(service._active_model_index, 1)

    def test_400_on_last_model_does_not_poison_next_calls_with_none(self) -> None:
        service = WhisperTranscriptionService(api_key="test-key")
        service._models = ["fallback-only"]
        service._active_model_index = 0
        service._client.audio.transcriptions.create = AsyncMock(
            side_effect=[
                _api_status_error(400, "Invalid file format"),
                _FakeResponse("recovered", "en"),
            ]
        )

        with self.assertRaises(RuntimeError) as first_error:
            asyncio.run(service.transcribe(_dummy_wav_bytes()))
        self.assertIn("Invalid file format", str(first_error.exception))
        self.assertNotIn("None", str(first_error.exception))
        self.assertEqual(service._active_model_index, 0)

        recovered = asyncio.run(service.transcribe(_dummy_wav_bytes()))
        self.assertEqual(recovered.text, "recovered")

    def test_gpt4o_transcribe_uses_json_response_format(self) -> None:
        service = WhisperTranscriptionService(api_key="test-key")
        request = service._build_request_kwargs(
            model_name="gpt-4o-mini-transcribe",
            audio_file=io.BytesIO(b"wav"),
            prompt="hello",
        )
        self.assertEqual(request["response_format"], "json")
        self.assertNotIn("temperature", request)

    def test_whisper_uses_verbose_json_response_format(self) -> None:
        service = WhisperTranscriptionService(api_key="test-key")
        request = service._build_request_kwargs(
            model_name="whisper-1",
            audio_file=io.BytesIO(b"wav"),
            prompt="hello",
        )
        self.assertEqual(request["response_format"], "verbose_json")
        self.assertEqual(request["temperature"], 0)


class RealtimeTranscriptionHelpersTests(unittest.TestCase):
    def test_resample_to_pcm16_24khz_outputs_audio_bytes(self) -> None:
        samples = np.linspace(-0.5, 0.5, 160, dtype=np.float32)
        pcm = RealtimeTranscriptionService._to_pcm16_24khz(samples, 16000)
        self.assertIsInstance(pcm, bytes)
        self.assertGreater(len(pcm), 0)
        self.assertEqual(len(pcm) % 2, 0)

    def test_merge_preview_text_collapses_spacing(self) -> None:
        merged = RealtimeTranscriptionService._merge_preview_text("hola", " mundo")
        self.assertEqual(merged, "hola mundo")


if __name__ == "__main__":
    unittest.main()
