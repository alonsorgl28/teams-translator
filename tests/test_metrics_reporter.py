from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from metrics_reporter import SessionMetricsReporter


class SessionMetricsReporterTests(unittest.TestCase):
    def test_writes_jsonl_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "session_metrics.jsonl"
            summary = Path(tmpdir) / "session_summary.json"
            reporter = SessionMetricsReporter(True, str(output), str(summary))
            reporter.start_session()
            reporter.record_segment(
                {
                    "event_type": "segment",
                    "latency_total_s": 1.2,
                    "had_fallback": False,
                }
            )
            reporter.record_segment(
                {
                    "event_type": "segment",
                    "latency_total_s": 2.8,
                    "had_fallback": True,
                }
            )
            reporter.record_error("translation", "timeout", audio_backlog=3, text_backlog=2)
            result = reporter.finalize_session()

            self.assertTrue(output.exists())
            self.assertTrue(summary.exists())
            self.assertEqual(result["segments_logged"], 2)
            self.assertEqual(result["fallback_segments"], 1)
            self.assertEqual(result["error_events"], 1)
            self.assertGreater(result["latency_p95_s"], 0.0)

            lines = output.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 3)
            parsed = [json.loads(line) for line in lines]
            self.assertEqual(parsed[0]["event_type"], "segment")
            self.assertEqual(parsed[-1]["event_type"], "error")

            saved_summary = json.loads(summary.read_text(encoding="utf-8"))
            self.assertEqual(saved_summary["segments_logged"], 2)

    def test_stage_counters_track_preview_commit_and_drop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "session_metrics.jsonl"
            summary = Path(tmpdir) / "session_summary.json"
            reporter = SessionMetricsReporter(True, str(output), str(summary))
            reporter.start_session()
            reporter.record_segment(
                {
                    "event_type": "segment",
                    "segment_stage": "preview",
                    "latency_total_s": 0.4,
                    "route": "normal",
                    "had_fallback": False,
                }
            )
            reporter.record_segment(
                {
                    "event_type": "segment",
                    "segment_stage": "commit",
                    "latency_total_s": 1.8,
                    "route": "premium",
                    "had_fallback": False,
                }
            )
            reporter.record_segment(
                {
                    "event_type": "segment",
                    "segment_stage": "drop",
                    "latency_total_s": 0.9,
                    "route": "drop",
                    "had_fallback": True,
                    "language_guard_triggered": True,
                }
            )
            result = reporter.finalize_session()
            self.assertEqual(result["segments_logged"], 3)
            self.assertEqual(result["segments_preview"], 1)
            self.assertEqual(result["segments_commit"], 1)
            self.assertEqual(result["segments_drop"], 1)
            self.assertEqual(result["premium_segments"], 1)
            self.assertEqual(result["language_guard_segments"], 1)
            self.assertEqual(result["fallback_segments"], 1)
            self.assertAlmostEqual(result["latency_avg_s"], 1.8, places=3)


if __name__ == "__main__":
    unittest.main()
