#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return float("nan")
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


def _stddev(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def _fmt(value: float | int | str | None) -> str:
    if value is None:
        return "N/D"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return "N/D"
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value)
    return "N/D"


def _load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        tests = data.get("tests", [])
        result: dict[str, dict[str, Any]] = {}
        for item in tests:
            test_id = str(item.get("test_id", "")).strip()
            if not test_id:
                continue
            result[test_id] = {
                "audio_tipo": item.get("audio_tipo", "N/D"),
                "duration_s": int(item.get("duration_min", 0) or 0) * 60 or "N/D",
                "url": item.get("url", "N/D"),
            }
        return result
    except Exception:
        result: dict[str, dict[str, Any]] = {}
        current: dict[str, Any] = {}
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("- "):
                if current.get("test_id"):
                    test_id = str(current["test_id"])
                    result[test_id] = {
                        "audio_tipo": current.get("audio_tipo", "N/D"),
                        "duration_s": int(current.get("duration_min", 0) or 0) * 60 or "N/D",
                        "url": current.get("url", "N/D"),
                    }
                current = {}
                line = line[2:]
            if ":" not in line:
                continue
            key, raw_value = line.split(":", 1)
            value = raw_value.strip().strip('"').strip("'")
            current[key.strip()] = value
        if current.get("test_id"):
            test_id = str(current["test_id"])
            result[test_id] = {
                "audio_tipo": current.get("audio_tipo", "N/D"),
                "duration_s": int(current.get("duration_min", 0) or 0) * 60 or "N/D",
                "url": current.get("url", "N/D"),
            }
        return result


def _quality_score(
    *,
    semantic_avg: float | None,
    language_purity: float | None,
    one_word_ratio: float | None,
    burstiness: float | None,
    fallback_ratio: float | None,
) -> float | None:
    if semantic_avg is None or language_purity is None:
        return None
    score = semantic_avg * 100.0
    score += max(0.0, (language_purity - 0.95) * 60.0)
    if one_word_ratio is not None:
        score -= one_word_ratio * 70.0
    if burstiness is not None:
        score -= min(15.0, burstiness * 10.0)
    if fallback_ratio is not None:
        score -= min(18.0, fallback_ratio * 45.0)
    return max(0.0, min(100.0, score))


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidate Loro benchmark metrics from session_metrics.jsonl.")
    parser.add_argument(
        "--metrics-jsonl",
        default=os.getenv("METRICS_OUTPUT_PATH", "./reports/session_metrics.jsonl"),
        help="Path to session_metrics.jsonl",
    )
    parser.add_argument(
        "--manifest",
        default=os.getenv("BENCHMARK_MANIFEST_PATH", "./bench/manifest_en_es.yaml"),
        help="Path to benchmark manifest YAML",
    )
    parser.add_argument(
        "--live-run-log",
        default=os.getenv("LIVE_RUN_LOG_PATH", "./reports/live_run.log"),
        help="Path to live_run.log (used as fallback when JSONL has gaps)",
    )
    parser.add_argument(
        "--output-csv",
        default="./reports/benchmark_metrics.csv",
        help="Output CSV path",
    )
    args = parser.parse_args()

    metrics_path = Path(args.metrics_jsonl)
    live_log_path = Path(args.live_run_log)
    manifest = _load_manifest(Path(args.manifest))
    output_csv = Path(args.output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if metrics_path.exists():
        for line in metrics_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event_type") != "segment":
                continue
            test_id = str(event.get("test_id") or "N/D")
            grouped[test_id].append(event)

    commit_event_count = 0
    for events in grouped.values():
        commit_event_count += sum(1 for e in events if str(e.get("segment_stage", "commit")) == "commit")

    if live_log_path.exists() and commit_event_count == 0:
        latency_pattern = re.compile(r"latency_s=([0-9]+(?:\.[0-9]+)?)")
        for line in live_log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = latency_pattern.search(line)
            if not match:
                continue
            latency = float(match.group(1))
            grouped["N/D"].append(
                {
                    "event_type": "segment",
                    "segment_stage": "commit",
                    "latency_total_s": latency,
                    "route": "normal",
                    "had_fallback": False,
                    "language_guard_triggered": False,
                }
            )

    all_ids = sorted(set(grouped.keys()) | set(manifest.keys()))
    if not all_ids:
        all_ids = ["N/D"]

    rows: list[dict[str, str]] = []
    for test_id in all_ids:
        events = grouped.get(test_id, [])
        commit_events = [e for e in events if str(e.get("segment_stage", "commit")) == "commit"]
        preview_events = [e for e in events if str(e.get("segment_stage", "commit")) == "preview"]
        drop_events = [e for e in events if str(e.get("segment_stage", "commit")) == "drop"]
        latency_values = [float(e.get("latency_total_s", 0.0) or 0.0) for e in commit_events]
        semantic_values = [float(e.get("semantic_score", 0.0) or 0.0) for e in commit_events if e.get("semantic_score") is not None]
        emit_intervals = [float(e.get("emit_interval_s", 0.0) or 0.0) for e in commit_events if float(e.get("emit_interval_s", 0.0) or 0.0) > 0]
        fallback_count = sum(1 for e in events if bool(e.get("had_fallback", False)))
        critical_errors = sum(
            1
            for e in drop_events
            if str(e.get("dropped_reason") or "")
            in {"language_guard", "semantic_low", "single_word_final", "commit_empty"}
        )
        language_purity = None
        if commit_events:
            pure_segments = sum(1 for e in commit_events if not bool(e.get("language_guard_triggered", False)))
            language_purity = pure_segments / len(commit_events)
        one_word_ratio = None
        if commit_events:
            one_word = 0
            for event in commit_events:
                text = str(event.get("rendered_text") or "")
                words = [w for w in text.split() if w]
                if len(words) == 1:
                    one_word += 1
            one_word_ratio = one_word / len(commit_events)
        premium_ratio = None
        if commit_events:
            premium_count = sum(1 for e in commit_events if str(e.get("route", "normal")) == "premium")
            premium_ratio = premium_count / len(commit_events)
        fallback_ratio = None
        if events:
            fallback_ratio = fallback_count / len(events)
        semantic_avg = (sum(semantic_values) / len(semantic_values)) if semantic_values else None
        score_calidad = _quality_score(
            semantic_avg=semantic_avg,
            language_purity=language_purity,
            one_word_ratio=one_word_ratio,
            burstiness=_stddev(emit_intervals) if emit_intervals else None,
            fallback_ratio=fallback_ratio,
        )

        manifest_item = manifest.get(test_id, {})
        row = {
            "test_id": test_id,
            "audio_tipo": str(manifest_item.get("audio_tipo", "N/D")),
            "duracion_s": _fmt(manifest_item.get("duration_s", "N/D")),
            "latency_avg": _fmt((sum(latency_values) / len(latency_values)) if latency_values else None),
            "latency_p95": _fmt(_percentile(latency_values, 0.95) if latency_values else None),
            "errores_criticos": _fmt(critical_errors if events else None),
            "fallback_segments": _fmt(fallback_count if events else None),
            "score_calidad": _fmt(score_calidad),
            "semantic_avg_0_1": _fmt(semantic_avg),
            "language_purity": _fmt(language_purity),
            "burstiness_s": _fmt(_stddev(emit_intervals) if emit_intervals else None),
            "one_word_ratio": _fmt(one_word_ratio),
            "premium_ratio": _fmt(premium_ratio),
            "preview_segments": _fmt(len(preview_events) if events else None),
            "commit_segments": _fmt(len(commit_events) if events else None),
            "drop_segments": _fmt(len(drop_events) if events else None),
        }
        rows.append(row)

    fieldnames = [
        "test_id",
        "audio_tipo",
        "duracion_s",
        "latency_avg",
        "latency_p95",
        "errores_criticos",
        "fallback_segments",
        "score_calidad",
        "semantic_avg_0_1",
        "language_purity",
        "burstiness_s",
        "one_word_ratio",
        "premium_ratio",
        "preview_segments",
        "commit_segments",
        "drop_segments",
    ]
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Benchmark metrics written to {output_csv}")


if __name__ == "__main__":
    main()
