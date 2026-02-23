from __future__ import annotations

import asyncio
import os
import unittest

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


if __name__ == "__main__":
    unittest.main()
