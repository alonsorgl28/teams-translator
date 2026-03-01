from __future__ import annotations

import asyncio
import io
import platform
import threading
import wave
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import numpy as np
import sounddevice as sd

from config_utils import read_float_env


@dataclass
class AudioChunk:
    captured_at: datetime
    duration_s: float
    wav_bytes: bytes


@dataclass
class StreamingAudioFrame:
    captured_at: datetime
    sample_rate: int
    samples: np.ndarray


class SystemAudioListener:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        output_queue: Optional[asyncio.Queue[AudioChunk]],
        chunk_seconds: float = 3.0,
        chunk_step_seconds: Optional[float] = None,
        sample_rate: int = 16000,
        channels: int = 1,
        preferred_device: Optional[str] = None,
        drop_oldest_on_full: bool = True,
        stream_output_queue: Optional[asyncio.Queue[StreamingAudioFrame]] = None,
    ) -> None:
        self._loop = loop
        self._output_queue = output_queue
        self._stream_output_queue = stream_output_queue
        self._chunk_seconds = chunk_seconds
        self._chunk_step_seconds = min(chunk_step_seconds or chunk_seconds, chunk_seconds)
        self._sample_rate = sample_rate
        self._channels = channels
        self._preferred_device = preferred_device
        self._drop_oldest_on_full = drop_oldest_on_full

        self._stream: Optional[sd.InputStream] = None
        self._buffer = np.empty((0,), dtype=np.float32)
        self._buffer_lock = threading.Lock()
        max_buffer_seconds = read_float_env("AUDIO_MAX_BUFFER_SECONDS", 12.0)
        self._max_buffer_frames = max(1, int(self._sample_rate * max_buffer_seconds))
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    @staticmethod
    def list_input_devices() -> list[str]:
        devices = sd.query_devices()
        names: list[str] = []
        for d in devices:
            if int(d.get("max_input_channels", 0)) > 0:
                names.append(str(d.get("name", "Unknown input device")))
        return names

    def start(self) -> None:
        if self._running:
            return

        device = self._resolve_input_device()
        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="float32",
            callback=self._audio_callback,
            device=device,
            blocksize=0,
        )
        self._stream.start()
        self._running = True

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._buffer_lock:
            self._buffer = np.empty((0,), dtype=np.float32)

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        del frames, time_info
        if status:
            # Keep listener alive even on non-fatal audio status updates.
            pass
        if not self._running:
            return

        mono = np.copy(indata[:, 0])
        samples_per_chunk = max(1, int(self._sample_rate * self._chunk_seconds))
        samples_per_step = max(1, int(self._sample_rate * self._chunk_step_seconds))
        chunks_to_publish: list[tuple[np.ndarray, datetime]] = []
        stream_frame = (mono.copy(), datetime.now())
        with self._buffer_lock:
            if not self._running:
                return
            if self._output_queue is not None:
                self._buffer = np.concatenate((self._buffer, mono))
                if self._buffer.shape[0] > self._max_buffer_frames:
                    self._buffer = self._buffer[-self._max_buffer_frames :]
                while self._buffer.shape[0] >= samples_per_chunk:
                    raw_chunk = self._buffer[:samples_per_chunk].copy()
                    self._buffer = self._buffer[samples_per_step:]
                    chunks_to_publish.append((raw_chunk, datetime.now()))

        if self._stream_output_queue is not None and self._running:
            raw_stream, captured_at = stream_frame
            self._loop.call_soon_threadsafe(self._publish_stream_frame, raw_stream, captured_at)

        for raw_chunk, captured_at in chunks_to_publish:
            if self._running:
                self._loop.call_soon_threadsafe(self._publish_chunk, raw_chunk, captured_at)

    def _publish_chunk(self, raw_chunk: np.ndarray, captured_at: datetime) -> None:
        if self._output_queue is None:
            return
        wav_bytes = self._to_wav_bytes(raw_chunk)
        chunk = AudioChunk(
            captured_at=captured_at,
            duration_s=self._chunk_seconds,
            wav_bytes=wav_bytes,
        )
        try:
            self._output_queue.put_nowait(chunk)
        except asyncio.QueueFull:
            if self._drop_oldest_on_full:
                # Drop oldest queue item to keep latency bounded.
                try:
                    self._output_queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                self._output_queue.put_nowait(chunk)
            else:
                # Lossless mode: enqueue asynchronously instead of dropping audio.
                self._loop.create_task(self._output_queue.put(chunk))

    def _publish_stream_frame(self, raw_chunk: np.ndarray, captured_at: datetime) -> None:
        if self._stream_output_queue is None:
            return
        frame = StreamingAudioFrame(
            captured_at=captured_at,
            sample_rate=self._sample_rate,
            samples=raw_chunk,
        )
        try:
            self._stream_output_queue.put_nowait(frame)
        except asyncio.QueueFull:
            try:
                self._stream_output_queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            self._stream_output_queue.put_nowait(frame)

    def _resolve_input_device(self) -> Optional[str]:
        if self._preferred_device:
            lowered_target = self._preferred_device.lower()
            for name in self.list_input_devices():
                if lowered_target in name.lower():
                    return name
            raise RuntimeError(
                f"SYSTEM_AUDIO_DEVICE '{self._preferred_device}' was not found among input devices."
            )

        keywords = self._default_device_keywords()
        if not keywords:
            raise RuntimeError("No system-audio capture keywords available for this platform.")

        for name in self.list_input_devices():
            lowered = name.lower()
            if any(key.lower() in lowered for key in keywords):
                return name
        raise RuntimeError(
            "No virtual system-audio input found. Configure VB-Cable (Windows) or BlackHole (macOS), "
            "or set SYSTEM_AUDIO_DEVICE."
        )

    @staticmethod
    def _default_device_keywords() -> list[str]:
        current = platform.system().lower()
        if current == "windows":
            return ["cable output", "vb-audio", "stereo mix"]
        if current == "darwin":
            return ["blackhole"]
        return ["monitor of"]

    def _to_wav_bytes(self, samples: np.ndarray) -> bytes:
        clamped = np.clip(samples, -1.0, 1.0)
        int16_samples = (clamped * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self._channels)
            wf.setsampwidth(2)
            wf.setframerate(self._sample_rate)
            wf.writeframes(int16_samples.tobytes())
        return buf.getvalue()
