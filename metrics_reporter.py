from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * ratio
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


class SessionMetricsReporter:
    def __init__(self, enabled: bool, output_path: str, summary_path: str, append_mode: bool = False) -> None:
        self._enabled = enabled
        self._output_path = Path(output_path)
        self._summary_path = Path(summary_path)
        self._append_mode = append_mode
        self._session_started_at: Optional[datetime] = None
        self._latencies: list[float] = []
        self._segments_logged = 0
        self._preview_segments = 0
        self._commit_segments = 0
        self._dropped_segments = 0
        self._fallback_segments = 0
        self._premium_segments = 0
        self._language_guard_segments = 0
        self._error_events = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def start_session(self) -> None:
        if not self._enabled:
            return
        self._session_started_at = datetime.now()
        self._latencies.clear()
        self._segments_logged = 0
        self._preview_segments = 0
        self._commit_segments = 0
        self._dropped_segments = 0
        self._fallback_segments = 0
        self._premium_segments = 0
        self._language_guard_segments = 0
        self._error_events = 0
        self._ensure_parent_dirs()
        if not self._append_mode:
            self._output_path.write_text("", encoding="utf-8")

    def record_segment(self, payload: dict[str, Any]) -> None:
        if not self._enabled:
            return
        stage = str(payload.get("segment_stage", "commit") or "commit")
        latency = float(payload.get("latency_total_s", 0.0) or 0.0)
        self._segments_logged += 1
        if stage == "commit":
            self._latencies.append(latency)
            self._commit_segments += 1
        elif stage == "preview":
            self._preview_segments += 1
        elif stage == "drop":
            self._dropped_segments += 1
        if bool(payload.get("had_fallback", False)):
            self._fallback_segments += 1
        if str(payload.get("route", "normal")) == "premium":
            self._premium_segments += 1
        if bool(payload.get("language_guard_triggered", False)):
            self._language_guard_segments += 1
        self._append_jsonl(payload)

    def record_error(self, stage: str, error: str, audio_backlog: int, text_backlog: int) -> None:
        if not self._enabled:
            return
        self._error_events += 1
        self._append_jsonl(
            {
                "event_type": "error",
                "recorded_at": datetime.now().isoformat(timespec="milliseconds"),
                "stage": stage,
                "error": error,
                "audio_backlog": audio_backlog,
                "text_backlog": text_backlog,
            }
        )

    def snapshot(self) -> dict[str, float]:
        if not self._latencies and self._error_events == 0:
            return {
                "avg_latency_s": 0.0,
                "p95_latency_s": 0.0,
                "issue_rate_pct": 0.0,
                "premium_ratio": 0.0,
                "drop_ratio_pct": 0.0,
            }
        base = max(1, self._commit_segments + self._dropped_segments + self._error_events)
        issues = self._fallback_segments + self._error_events
        return {
            "avg_latency_s": (sum(self._latencies) / len(self._latencies)) if self._latencies else 0.0,
            "p95_latency_s": _percentile(self._latencies, 0.95) if self._latencies else 0.0,
            "issue_rate_pct": (issues / base) * 100.0,
            "premium_ratio": self._premium_segments / max(1, self._segments_logged),
            "drop_ratio_pct": (self._dropped_segments / max(1, self._segments_logged)) * 100.0,
        }

    def finalize_session(self) -> dict[str, Any]:
        if not self._enabled:
            return {}
        now = datetime.now()
        started = self._session_started_at or now
        duration_s = max(0.0, (now - started).total_seconds())
        avg_latency = sum(self._latencies) / len(self._latencies) if self._latencies else 0.0
        summary = {
            "session_started_at": started.isoformat(timespec="milliseconds"),
            "session_ended_at": now.isoformat(timespec="milliseconds"),
            "session_duration_s": duration_s,
            "segments_logged": self._segments_logged,
            "segments_preview": self._preview_segments,
            "segments_commit": self._commit_segments,
            "segments_drop": self._dropped_segments,
            "fallback_segments": self._fallback_segments,
            "premium_segments": self._premium_segments,
            "language_guard_segments": self._language_guard_segments,
            "premium_ratio": (self._premium_segments / max(1, self._segments_logged)),
            "error_events": self._error_events,
            "issue_rate_pct": (
                (self._fallback_segments + self._error_events)
                / max(1, self._commit_segments + self._dropped_segments + self._error_events)
            )
            * 100.0,
            "latency_avg_s": avg_latency,
            "latency_p50_s": _percentile(self._latencies, 0.50),
            "latency_p95_s": _percentile(self._latencies, 0.95),
            "latency_max_s": max(self._latencies) if self._latencies else 0.0,
        }
        self._write_summary(summary)
        return summary

    def _ensure_parent_dirs(self) -> None:
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._summary_path.parent.mkdir(parents=True, exist_ok=True)

    def _append_jsonl(self, payload: dict[str, Any]) -> None:
        self._ensure_parent_dirs()
        line = json.dumps(payload, ensure_ascii=False)
        with self._output_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.write("\n")

    def _write_summary(self, summary: dict[str, Any]) -> None:
        self._ensure_parent_dirs()
        with self._summary_path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
