#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from replay_tools import load_replay_manifest, load_subtitle_cues, match_reference_cue


def _fmt_float(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "N/D"
    return f"{value:.3f}"


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


def _build_group_key(event: dict[str, Any]) -> str:
    audio_t0 = float(event.get("audio_t0", 0.0) or 0.0)
    audio_t1 = float(event.get("audio_t1", 0.0) or 0.0)
    source = str(event.get("source_text_sanitized") or event.get("source_text") or "")
    return f"{audio_t0:.3f}|{audio_t1:.3f}|{source}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare replay events against reference subtitles.")
    parser.add_argument(
        "--replay-jsonl",
        default="./reports/replay_events.jsonl",
        help="Path to replay events JSONL",
    )
    parser.add_argument(
        "--manifest",
        default="./bench/replay_manifest.yaml",
        help="Path to replay manifest YAML",
    )
    parser.add_argument("--fixture-id", default="", help="Optional fixture ID filter")
    parser.add_argument(
        "--reference-path",
        default="",
        help="Override reference caption path (VTT/SRT/JSON)",
    )
    parser.add_argument(
        "--output-csv",
        default="./reports/replay_diff.csv",
        help="Output CSV path",
    )
    args = parser.parse_args()

    manifest = load_replay_manifest(Path(args.manifest).resolve())
    fixture_id = args.fixture_id.strip()
    reference_path = Path(args.reference_path).resolve() if args.reference_path.strip() else None
    if not reference_path and fixture_id and fixture_id in manifest and manifest[fixture_id].reference_caption_path:
        reference_path = Path(manifest[fixture_id].reference_caption_path)
    reference_cues = load_subtitle_cues(reference_path) if reference_path is not None and reference_path.exists() else []

    grouped: dict[str, dict[str, Any]] = {}
    for event in _load_events(Path(args.replay_jsonl).resolve()):
        if fixture_id and str(event.get("fixture_id") or "") != fixture_id:
            continue
        if event.get("event_type") != "segment":
            continue
        key = _build_group_key(event)
        row = grouped.setdefault(
            key,
            {
                "fixture_id": str(event.get("fixture_id") or "N/D"),
                "audio_t0": _fmt_float(float(event.get("audio_t0", 0.0) or 0.0)),
                "audio_t1": _fmt_float(float(event.get("audio_t1", 0.0) or 0.0)),
                "source_text_raw": str(event.get("source_text_raw") or ""),
                "source_text_sanitized": str(event.get("source_text_sanitized") or event.get("source_text") or ""),
                "translated_preview": "",
                "translated_commit": "",
                "render_t_preview": "N/D",
                "render_t_commit": "N/D",
                "latency_source_s": "N/D",
                "latency_commit_s": "N/D",
                "route": str(event.get("route") or "normal"),
                "drop_reason": "",
                "reference_text": str(event.get("reference_text") or ""),
                "reference_t0": _fmt_float(event.get("reference_t0")),
                "reference_t1": _fmt_float(event.get("reference_t1")),
            },
        )
        row["route"] = str(event.get("route") or row["route"])
        if str(event.get("segment_stage") or "") == "preview":
            row["translated_preview"] = str(event.get("rendered_text") or row["translated_preview"])
            row["render_t_preview"] = _fmt_float(float(event.get("render_t", 0.0) or 0.0))
            row["latency_source_s"] = _fmt_float(float(event.get("transcription_time_s", 0.0) or 0.0))
        elif str(event.get("segment_stage") or "") == "commit":
            row["translated_commit"] = str(event.get("rendered_text") or row["translated_commit"])
            row["render_t_commit"] = _fmt_float(float(event.get("render_t", 0.0) or 0.0))
            row["latency_commit_s"] = _fmt_float(float(event.get("latency_total_s", 0.0) or 0.0))
        elif str(event.get("segment_stage") or "") == "drop":
            row["drop_reason"] = str(event.get("dropped_reason") or row["drop_reason"])

    if reference_cues:
        for row in grouped.values():
            if row["reference_text"]:
                continue
            audio_t0 = float(row["audio_t0"]) if row["audio_t0"] != "N/D" else 0.0
            audio_t1 = float(row["audio_t1"]) if row["audio_t1"] != "N/D" else audio_t0
            cue = match_reference_cue(reference_cues, audio_t0, audio_t1)
            if cue is None:
                continue
            row["reference_text"] = cue.text
            row["reference_t0"] = _fmt_float(cue.start_s)
            row["reference_t1"] = _fmt_float(cue.end_s)

    output_path = Path(args.output_csv).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "fixture_id",
        "audio_t0",
        "audio_t1",
        "source_text_raw",
        "source_text_sanitized",
        "translated_preview",
        "translated_commit",
        "render_t_preview",
        "render_t_commit",
        "latency_source_s",
        "latency_commit_s",
        "route",
        "drop_reason",
        "reference_text",
        "reference_t0",
        "reference_t1",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in sorted(grouped.values(), key=lambda value: float(value["audio_t0"]) if value["audio_t0"] != "N/D" else 0.0):
            writer.writerow(row)

    print(f"Replay diff written to {output_path}")
    print(f"rows={len(grouped)}")


if __name__ == "__main__":
    main()
