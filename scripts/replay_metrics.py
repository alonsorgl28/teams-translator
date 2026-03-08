#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any


def _load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * ratio
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _fmt(value: float | None) -> str:
    if value is None:
        return "N/D"
    return f"{value:.3f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize replay benchmark metrics from replay_events.jsonl")
    parser.add_argument(
        "--replay-jsonl",
        default="./reports/replay_events.jsonl",
        help="Path to replay events JSONL",
    )
    parser.add_argument("--fixture-id", default="", help="Optional fixture ID filter")
    parser.add_argument(
        "--output-csv",
        default="./reports/replay_metrics.csv",
        help="Output CSV path",
    )
    args = parser.parse_args()

    events = _load_events(Path(args.replay_jsonl).resolve())
    fixture_filter = args.fixture_id.strip()
    if fixture_filter:
        events = [event for event in events if str(event.get("fixture_id") or "") == fixture_filter]

    asr_preview = [event for event in events if event.get("event_type") == "asr" and event.get("asr_stage") == "preview"]
    asr_stable = [event for event in events if event.get("event_type") == "asr" and event.get("asr_stage") == "stable"]
    segments = [event for event in events if event.get("event_type") == "segment"]
    preview_segments = [event for event in segments if event.get("segment_stage") == "preview"]
    commit_segments = [event for event in segments if event.get("segment_stage") == "commit"]
    drop_segments = [event for event in segments if event.get("segment_stage") == "drop"]

    commit_latencies = [float(event.get("latency_total_s", 0.0) or 0.0) for event in commit_segments]
    source_latencies = [float(event.get("latency_source_s", 0.0) or 0.0) for event in asr_stable]
    emit_gaps = [float(event.get("emit_interval_s", 0.0) or 0.0) for event in commit_segments if float(event.get("emit_interval_s", 0.0) or 0.0) > 0.0]
    premium_commits = [event for event in commit_segments if str(event.get("route") or "") == "premium"]
    language_guard_hits = sum(1 for event in segments if bool(event.get("language_guard_triggered", False)))

    fixture_id = fixture_filter or (str(events[0].get("fixture_id") or "N/D") if events else "N/D")
    metrics_row = {
        "fixture_id": fixture_id,
        "asr_preview_events": str(len(asr_preview)),
        "asr_stable_events": str(len(asr_stable)),
        "preview_segments": str(len(preview_segments)),
        "commit_segments": str(len(commit_segments)),
        "drop_segments": str(len(drop_segments)),
        "source_latency_p50_s": _fmt(_percentile(source_latencies, 0.5)),
        "source_latency_p95_s": _fmt(_percentile(source_latencies, 0.95)),
        "commit_latency_p50_s": _fmt(_percentile(commit_latencies, 0.5)),
        "commit_latency_p95_s": _fmt(_percentile(commit_latencies, 0.95)),
        "emit_gap_stddev_s": _fmt(statistics.pstdev(emit_gaps) if len(emit_gaps) >= 2 else None),
        "premium_commit_ratio": _fmt((len(premium_commits) / len(commit_segments)) if commit_segments else None),
        "language_guard_hits": str(language_guard_hits),
    }

    output_path = Path(args.output_csv).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(metrics_row.keys()))
        writer.writeheader()
        writer.writerow(metrics_row)

    print(f"Replay metrics written to {output_path}")
    for key, value in metrics_row.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
