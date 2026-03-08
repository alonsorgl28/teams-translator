from __future__ import annotations

import asyncio
import os
import unittest
from datetime import datetime

import numpy as np

from audio_listener import SystemAudioListener


class AudioBufferLimitTests(unittest.TestCase):
    def test_internal_buffer_is_capped(self) -> None:
        original = os.environ.get("AUDIO_MAX_BUFFER_SECONDS")
        os.environ["AUDIO_MAX_BUFFER_SECONDS"] = "0.05"
        loop = asyncio.new_event_loop()
        try:
            queue: asyncio.Queue = asyncio.Queue(maxsize=2)
            listener = SystemAudioListener(
                loop=loop,
                output_queue=queue,
                sample_rate=100,
                chunk_seconds=1.0,
                chunk_step_seconds=1.0,
                channels=1,
            )
            listener._running = True
            indata = np.ones((30, 1), dtype=np.float32)
            listener._audio_callback(indata, frames=30, time_info=None, status=None)

            self.assertLessEqual(listener._buffer.shape[0], listener._max_buffer_frames)
            listener.stop()
        finally:
            loop.close()
            if original is None:
                os.environ.pop("AUDIO_MAX_BUFFER_SECONDS", None)
            else:
                os.environ["AUDIO_MAX_BUFFER_SECONDS"] = original

    def test_silence_filter_skips_quiet_chunk(self) -> None:
        original_enabled = os.environ.get("AUDIO_SILENCE_FILTER_ENABLED")
        original_rms = os.environ.get("AUDIO_MIN_CHUNK_RMS")
        original_peak = os.environ.get("AUDIO_MIN_CHUNK_PEAK")
        loop = asyncio.new_event_loop()
        try:
            os.environ["AUDIO_SILENCE_FILTER_ENABLED"] = "1"
            os.environ["AUDIO_MIN_CHUNK_RMS"] = "0.01"
            os.environ["AUDIO_MIN_CHUNK_PEAK"] = "0.05"
            queue: asyncio.Queue = asyncio.Queue(maxsize=2)
            listener = SystemAudioListener(
                loop=loop,
                output_queue=queue,
                sample_rate=16000,
                chunk_seconds=1.0,
                chunk_step_seconds=1.0,
                channels=1,
            )
            quiet = np.zeros((16000,), dtype=np.float32)
            listener._publish_chunk(quiet, captured_at=datetime.now())
            self.assertTrue(queue.empty())
        finally:
            loop.close()
            if original_enabled is None:
                os.environ.pop("AUDIO_SILENCE_FILTER_ENABLED", None)
            else:
                os.environ["AUDIO_SILENCE_FILTER_ENABLED"] = original_enabled
            if original_rms is None:
                os.environ.pop("AUDIO_MIN_CHUNK_RMS", None)
            else:
                os.environ["AUDIO_MIN_CHUNK_RMS"] = original_rms
            if original_peak is None:
                os.environ.pop("AUDIO_MIN_CHUNK_PEAK", None)
            else:
                os.environ["AUDIO_MIN_CHUNK_PEAK"] = original_peak


if __name__ == "__main__":
    unittest.main()
