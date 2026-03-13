from __future__ import annotations

import asyncio
import io
import os
import platform
import threading
import time
import wave
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import numpy as np
import sounddevice as sd

from config_utils import read_bool_env, read_float_env, read_int_env
from vad import SileroVadSegmenter


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
        self._silence_filter_enabled = read_bool_env("AUDIO_SILENCE_FILTER_ENABLED", True)
        self._min_chunk_rms = read_float_env("AUDIO_MIN_CHUNK_RMS", 0.0035)
        self._min_chunk_peak = read_float_env("AUDIO_MIN_CHUNK_PEAK", 0.012)
        self._speech_hold_chunks = max(0, read_int_env("AUDIO_SPEECH_HOLD_CHUNKS", 1))
        self._speech_hold_remaining = 0
        self._vad_enabled = read_bool_env("VAD_ENABLED", False)
        self._vad: Optional[SileroVadSegmenter] = None
        if self._vad_enabled:
            self._vad = SileroVadSegmenter(sample_rate=self._sample_rate)
        self._replay_audio_path = (os.getenv("REPLAY_AUDIO_PATH") or "").strip()
        self._replay_speed = max(0.05, read_float_env("REPLAY_SPEED", 1.0))
        self._replay_frame_seconds = max(0.02, read_float_env("REPLAY_FRAME_SECONDS", 0.04))
        self._replay_thread: Optional[threading.Thread] = None
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

        if self._replay_audio_path:
            self._running = True
            self._replay_thread = threading.Thread(target=self._replay_worker, name="loro-audio-replay", daemon=True)
            self._replay_thread.start()
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
        if self._replay_thread is not None and self._replay_thread.is_alive() and threading.current_thread() is not self._replay_thread:
            self._replay_thread.join(timeout=1.0)
        self._replay_thread = None
        # Flush any remaining VAD speech buffer
        if self._vad is not None:
            remaining = self._vad.flush()
            if remaining is not None and self._output_queue is not None:
                self._loop.call_soon_threadsafe(self._publish_chunk, remaining, datetime.now())
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

        # Stream frames for realtime transcription (independent of VAD)
        if self._stream_output_queue is not None and self._running:
            stream_frame_data = mono.copy()
            captured_at = datetime.now()
            self._loop.call_soon_threadsafe(self._publish_stream_frame, stream_frame_data, captured_at)

        if self._vad_enabled and self._vad is not None:
            self._audio_callback_vad(mono)
        else:
            self._audio_callback_fixed(mono)

    def _audio_callback_vad(self, mono: np.ndarray) -> None:
        """VAD-based segmentation: emit chunks on speech boundaries."""
        if self._output_queue is None:
            return
        with self._buffer_lock:
            if not self._running:
                return
            completed_segments = self._vad.process_audio(mono)
        for segment in completed_segments:
            if self._running:
                self._loop.call_soon_threadsafe(self._publish_chunk, segment, datetime.now())

    def _audio_callback_fixed(self, mono: np.ndarray) -> None:
        """Original fixed-time segmentation."""
        samples_per_chunk = max(1, int(self._sample_rate * self._chunk_seconds))
        samples_per_step = max(1, int(self._sample_rate * self._chunk_step_seconds))
        chunks_to_publish: list[tuple[np.ndarray, datetime]] = []
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

        for raw_chunk, captured_at in chunks_to_publish:
            if self._running:
                self._loop.call_soon_threadsafe(self._publish_chunk, raw_chunk, captured_at)

    def _publish_chunk(self, raw_chunk: np.ndarray, captured_at: datetime) -> None:
        if self._output_queue is None:
            return
        if self._should_skip_silent_chunk(raw_chunk):
            return
        wav_bytes = self._to_wav_bytes(raw_chunk)
        duration_s = raw_chunk.shape[0] / max(1, self._sample_rate)
        chunk = AudioChunk(
            captured_at=captured_at,
            duration_s=duration_s,
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

    def _should_skip_silent_chunk(self, raw_chunk: np.ndarray) -> bool:
        if not self._silence_filter_enabled:
            return False
        if raw_chunk.size == 0:
            return True

        rms = float(np.sqrt(np.mean(np.square(raw_chunk, dtype=np.float64))))
        peak = float(np.max(np.abs(raw_chunk)))
        if rms >= self._min_chunk_rms or peak >= self._min_chunk_peak:
            self._speech_hold_remaining = self._speech_hold_chunks
            return False
        if self._speech_hold_remaining > 0:
            self._speech_hold_remaining -= 1
            return False
        return True

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

    def _replay_worker(self) -> None:
        try:
            with wave.open(self._replay_audio_path, "rb") as handle:
                sample_rate = int(handle.getframerate())
                channels = int(handle.getnchannels())
                sample_width = int(handle.getsampwidth())
                frame_count = max(1, int(sample_rate * self._replay_frame_seconds))
                while self._running:
                    raw_frames = handle.readframes(frame_count)
                    if not raw_frames:
                        break
                    mono = self._frames_to_mono(raw_frames, sample_width=sample_width, channels=channels)
                    if mono.size == 0:
                        continue
                    mono = self._resample_if_needed(mono, source_rate=sample_rate)
                    if mono.size == 0:
                        continue
                    block = mono.reshape(-1, 1)
                    self._audio_callback(block, frames=block.shape[0], time_info=None, status=None)
                    sleep_s = (block.shape[0] / max(1, self._sample_rate)) / self._replay_speed
                    time.sleep(max(0.0, sleep_s))
        finally:
            self._running = False

    @staticmethod
    def _frames_to_mono(raw_frames: bytes, *, sample_width: int, channels: int) -> np.ndarray:
        if sample_width == 2:
            data = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32) / 32768.0
        elif sample_width == 4:
            data = np.frombuffer(raw_frames, dtype=np.int32).astype(np.float32) / 2147483648.0
        elif sample_width == 1:
            data = (np.frombuffer(raw_frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        else:
            return np.empty((0,), dtype=np.float32)
        if channels > 1:
            frames = data.size // channels
            if frames <= 0:
                return np.empty((0,), dtype=np.float32)
            data = data[: frames * channels].reshape(frames, channels).mean(axis=1)
        return data.astype(np.float32, copy=False)

    def _resample_if_needed(self, samples: np.ndarray, *, source_rate: int) -> np.ndarray:
        if source_rate == self._sample_rate or samples.size == 0:
            return samples
        duration_s = samples.size / max(1, source_rate)
        target_size = max(1, int(duration_s * self._sample_rate))
        source_x = np.linspace(0.0, 1.0, num=samples.size, endpoint=False)
        target_x = np.linspace(0.0, 1.0, num=target_size, endpoint=False)
        resampled = np.interp(target_x, source_x, samples)
        return resampled.astype(np.float32)

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
