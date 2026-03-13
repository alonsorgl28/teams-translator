"""Voice Activity Detection using Silero VAD.

Provides streaming speech segmentation: instead of cutting audio at fixed
time intervals, it accumulates samples while speech is detected and emits
complete utterances when the speaker pauses.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import torch

from config_utils import read_float_env, read_int_env


class SileroVadSegmenter:
    """Streaming VAD that buffers audio during speech and emits on silence."""

    def __init__(self, sample_rate: int = 16000) -> None:
        self._sample_rate = sample_rate
        self._threshold = read_float_env("VAD_THRESHOLD", 0.45)
        self._min_speech_ms = read_int_env("VAD_MIN_SPEECH_MS", 250)
        self._min_silence_ms = read_int_env("VAD_MIN_SILENCE_MS", 300)
        self._speech_pad_ms = read_int_env("VAD_SPEECH_PAD_MS", 60)
        self._max_speech_s = read_float_env("VAD_MAX_SPEECH_SECONDS", 8.0)
        self._min_chunk_s = read_float_env("VAD_MIN_CHUNK_SECONDS", 0.5)

        # Silero VAD expects 512 samples at 16 kHz (32 ms per frame)
        self._frame_size = 512 if sample_rate == 16000 else 256

        self._model = self._load_model()

        # Streaming state
        self._speech_active = False
        self._speech_buffer: list[np.ndarray] = []
        self._speech_samples = 0
        self._silence_samples = 0
        self._pad_buffer: list[np.ndarray] = []
        self._pad_samples = 0
        self._max_pad_samples = int(self._sample_rate * self._speech_pad_ms / 1000)
        self._min_speech_samples = int(self._sample_rate * self._min_speech_ms / 1000)
        self._min_silence_samples = int(self._sample_rate * self._min_silence_ms / 1000)
        self._max_speech_samples = int(self._sample_rate * self._max_speech_s)
        self._min_chunk_samples = int(self._sample_rate * self._min_chunk_s)

        # Internal frame accumulator for feeding exact frame sizes to the model
        self._frame_accumulator = np.empty((0,), dtype=np.float32)

    @staticmethod
    def _load_model():
        try:
            from silero_vad import load_silero_vad
            model = load_silero_vad()
            return model
        except ImportError:
            model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-vad:master",
                model="silero_vad",
                force_reload=False,
                onnx=False,
            )
            return model

    def reset(self) -> None:
        """Reset all streaming state."""
        self._speech_active = False
        self._speech_buffer.clear()
        self._speech_samples = 0
        self._silence_samples = 0
        self._pad_buffer.clear()
        self._pad_samples = 0
        self._frame_accumulator = np.empty((0,), dtype=np.float32)
        self._model.reset_states()

    def process_audio(self, mono_samples: np.ndarray) -> list[np.ndarray]:
        """Feed raw mono float32 audio and return completed utterances.

        Each returned ndarray is a complete speech segment ready for STT.
        Most calls return an empty list; a segment is emitted only when
        the speaker pauses or the max duration is reached.
        """
        self._frame_accumulator = np.concatenate((self._frame_accumulator, mono_samples))
        completed: list[np.ndarray] = []

        while self._frame_accumulator.shape[0] >= self._frame_size:
            frame = self._frame_accumulator[: self._frame_size]
            self._frame_accumulator = self._frame_accumulator[self._frame_size :]

            speech_prob = self._get_speech_prob(frame)
            is_speech = speech_prob >= self._threshold

            if is_speech:
                self._silence_samples = 0
                if not self._speech_active:
                    # Speech just started — prepend padding
                    self._speech_active = True
                    if self._pad_buffer:
                        self._speech_buffer.extend(self._pad_buffer)
                        self._speech_samples += self._pad_samples
                    self._pad_buffer.clear()
                    self._pad_samples = 0
                self._speech_buffer.append(frame)
                self._speech_samples += frame.shape[0]

                # Force-emit if speech is too long (someone talking nonstop)
                if self._speech_samples >= self._max_speech_samples:
                    segment = self._emit_segment()
                    if segment is not None:
                        completed.append(segment)
            else:
                if self._speech_active:
                    # Still in speech, counting silence
                    self._speech_buffer.append(frame)
                    self._speech_samples += frame.shape[0]
                    self._silence_samples += frame.shape[0]

                    if self._silence_samples >= self._min_silence_samples:
                        # Enough silence — emit the utterance
                        segment = self._emit_segment()
                        if segment is not None:
                            completed.append(segment)
                else:
                    # Not speaking — keep a rolling pad buffer
                    self._pad_buffer.append(frame)
                    self._pad_samples += frame.shape[0]
                    while self._pad_samples > self._max_pad_samples and self._pad_buffer:
                        removed = self._pad_buffer.pop(0)
                        self._pad_samples -= removed.shape[0]

        return completed

    def flush(self) -> Optional[np.ndarray]:
        """Flush any remaining speech buffer (e.g. on stop)."""
        if self._speech_buffer and self._speech_samples >= self._min_chunk_samples:
            return self._emit_segment()
        self.reset()
        return None

    def _emit_segment(self) -> Optional[np.ndarray]:
        """Concatenate buffered speech into a single array and reset state."""
        if not self._speech_buffer:
            return None
        segment = np.concatenate(self._speech_buffer)
        speech_samples = self._speech_samples

        self._speech_buffer.clear()
        self._speech_samples = 0
        self._silence_samples = 0
        self._speech_active = False

        # Drop segments that are too short (likely noise)
        if speech_samples < self._min_chunk_samples:
            return None
        # Drop segments shorter than min_speech_ms (not enough actual speech)
        if speech_samples < self._min_speech_samples:
            return None
        return segment

    def _get_speech_prob(self, frame: np.ndarray) -> float:
        """Run Silero VAD on a single frame."""
        try:
            tensor = torch.FloatTensor(frame)
            with torch.no_grad():
                prob = self._model(tensor, self._sample_rate)
            return float(prob)
        except Exception as exc:  # noqa: BLE001
            logging.warning("vad_inference_error: %s", exc)
            return 0.0
