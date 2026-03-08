from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from replay_tools import load_replay_manifest, load_subtitle_cues, match_reference_cue


class ReplayToolsTests(unittest.TestCase):
    def test_load_replay_manifest_parses_flat_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "replay_manifest.yaml"
            manifest.write_text(
                "\n".join(
                    [
                        "fixtures:",
                        "  - fixture_id: demo_01",
                        '    title: "Demo"',
                        '    source_url: "https://example.com/video"',
                        "    clip_start_s: 12.5",
                        "    duration_s: 45",
                        '    audio_path: "./fixture.wav"',
                    ]
                ),
                encoding="utf-8",
            )
            fixtures = load_replay_manifest(manifest)
            self.assertIn("demo_01", fixtures)
            self.assertEqual(fixtures["demo_01"].title, "Demo")
            self.assertAlmostEqual(fixtures["demo_01"].clip_start_s, 12.5)
            self.assertTrue(fixtures["demo_01"].audio_path.endswith("fixture.wav"))

    def test_load_subtitle_cues_parses_vtt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "reference.vtt"
            path.write_text(
                "\n".join(
                    [
                        "WEBVTT",
                        "",
                        "00:00:01.000 --> 00:00:03.000",
                        "hello there",
                        "",
                        "00:00:03.000 --> 00:00:05.000",
                        "general kenobi",
                    ]
                ),
                encoding="utf-8",
            )
            cues = load_subtitle_cues(path)
            self.assertEqual(len(cues), 2)
            self.assertEqual(cues[0].text, "hello there")
            self.assertAlmostEqual(cues[1].start_s, 3.0)

    def test_match_reference_cue_prefers_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "reference.vtt"
            path.write_text(
                "\n".join(
                    [
                        "WEBVTT",
                        "",
                        "00:00:01.000 --> 00:00:03.000",
                        "first line",
                        "",
                        "00:00:03.000 --> 00:00:06.000",
                        "second line",
                    ]
                ),
                encoding="utf-8",
            )
            cues = load_subtitle_cues(path)
            cue = match_reference_cue(cues, 3.4, 4.1)
            self.assertIsNotNone(cue)
            assert cue is not None
            self.assertEqual(cue.text, "second line")


if __name__ == "__main__":
    unittest.main()
