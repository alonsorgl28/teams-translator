#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from segment_quality import SegmentQualityGate

def _load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _english_tokens(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[a-z0-9']+", text or "")]


def _overlap_ratio(source_text: str, reference_text: str) -> float | None:
    source_tokens = _english_tokens(source_text)
    reference_tokens = _english_tokens(reference_text)
    if not source_tokens or not reference_tokens:
        return None
    source_set = set(source_tokens)
    reference_set = set(reference_tokens)
    return len(source_set & reference_set) / max(1, len(reference_set))


def _classify_commit(event: dict[str, Any]) -> tuple[str, bool]:
    source_confidence = float(event.get("source_confidence", 0.0) or 0.0)
    source_incomplete = bool(event.get("source_incomplete", False))
    mixed_script = bool(event.get("mixed_script_detected", False))
    non_target = bool(event.get("non_target_language_detected", False))
    too_similar = bool(event.get("translation_too_similar_to_source", False))
    semantic_drift = float(event.get("semantic_drift_score", 0.0) or 0.0)
    reference_overlap = _overlap_ratio(
        str(event.get("source_text_sanitized") or event.get("source_text") or ""),
        str(event.get("reference_text") or ""),
    )

    if mixed_script or non_target or too_similar:
        return "translation", True
    if source_confidence < 0.39 or source_incomplete:
        return "stt_or_merge", False
    if reference_overlap is not None and reference_overlap < 0.45:
        return "stt_or_merge", False
    if semantic_drift > 0.30:
        return "commit_guard_gap", True
    return "ok", False


def _summarize(events: list[dict[str, Any]], fixture_id: str) -> dict[str, Any]:
    gate = SegmentQualityGate()
    filtered = [event for event in events if not fixture_id or str(event.get("fixture_id") or "") == fixture_id]
    commit_segments = [event for event in filtered if event.get("event_type") == "segment" and event.get("segment_stage") == "commit"]
    drop_segments = [event for event in filtered if event.get("event_type") == "segment" and event.get("segment_stage") == "drop"]
    cause_counter: Counter[str] = Counter()
    unsafe_commits = 0
    detailed_rows: list[dict[str, str]] = []
    source_confidences: list[float] = []
    drift_scores: list[float] = []

    for event in commit_segments:
        if "source_confidence" not in event or "semantic_drift_score" not in event:
            signals = gate.inspect_segment(
                source_text=str(event.get("source_text_sanitized") or event.get("source_text") or ""),
                translated_text=str(event.get("rendered_text") or ""),
                target_language="Spanish",
            )
            event = {
                **event,
                "source_confidence": signals.source_confidence,
                "source_incomplete": signals.source_incomplete,
                "mixed_script_detected": signals.mixed_script_detected,
                "non_target_language_detected": signals.non_target_language_detected,
                "translation_too_similar_to_source": signals.translation_too_similar_to_source,
                "semantic_drift_score": signals.semantic_drift_score,
            }
        cause, unsafe = _classify_commit(event)
        cause_counter[cause] += 1
        if unsafe:
            unsafe_commits += 1
        source_confidence = float(event.get("source_confidence", 0.0) or 0.0)
        semantic_drift = float(event.get("semantic_drift_score", 0.0) or 0.0)
        source_confidences.append(source_confidence)
        drift_scores.append(semantic_drift)
        detailed_rows.append(
            {
                "fixture_id": str(event.get("fixture_id") or "N/D"),
                "audio_t0": f"{float(event.get('audio_t0', 0.0) or 0.0):.3f}",
                "audio_t1": f"{float(event.get('audio_t1', 0.0) or 0.0):.3f}",
                "source_text_sanitized": str(event.get("source_text_sanitized") or event.get("source_text") or ""),
                "rendered_text": str(event.get("rendered_text") or ""),
                "reference_text": str(event.get("reference_text") or ""),
                "source_confidence": f"{source_confidence:.3f}",
                "semantic_drift_score": f"{semantic_drift:.3f}",
                "mixed_script_detected": "1" if bool(event.get("mixed_script_detected", False)) else "0",
                "non_target_language_detected": "1" if bool(event.get("non_target_language_detected", False)) else "0",
                "translation_too_similar_to_source": (
                    "1" if bool(event.get("translation_too_similar_to_source", False)) else "0"
                ),
                "root_cause": cause,
            }
        )

    total_commits = len(commit_segments)
    mixed_script_rate = sum(1 for event in commit_segments if bool(event.get("mixed_script_detected", False))) / max(1, total_commits)
    non_spanish_commit_rate = (
        sum(1 for event in commit_segments if bool(event.get("non_target_language_detected", False))) / max(1, total_commits)
    )
    hallucinated_commit_rate = unsafe_commits / max(1, total_commits)
    one_word_commit_rate = (
        sum(1 for event in commit_segments if len(str(event.get("rendered_text") or "").split()) <= 1) / max(1, total_commits)
    )
    top_root_cause = cause_counter.most_common(1)[0][0] if cause_counter else "N/D"

    return {
        "fixture_id": fixture_id or (str(filtered[0].get("fixture_id") or "N/D") if filtered else "N/D"),
        "commit_segments": total_commits,
        "drop_segments": len(drop_segments),
        "mixed_script_rate": mixed_script_rate,
        "non_spanish_commit_rate": non_spanish_commit_rate,
        "hallucinated_commit_rate": hallucinated_commit_rate,
        "one_word_commit_rate": one_word_commit_rate,
        "avg_source_confidence": statistics.mean(source_confidences) if source_confidences else 0.0,
        "avg_semantic_drift": statistics.mean(drift_scores) if drift_scores else 0.0,
        "top_root_cause": top_root_cause,
        "cause_counter": cause_counter,
        "detail_rows": detailed_rows,
    }


def _fmt_ratio(value: float) -> str:
    return f"{value * 100:.1f}%"


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "fixture_id",
        "audio_t0",
        "audio_t1",
        "source_text_sanitized",
        "rendered_text",
        "reference_text",
        "source_confidence",
        "semantic_drift_score",
        "mixed_script_detected",
        "non_target_language_detected",
        "translation_too_similar_to_source",
        "root_cause",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _summary_lines(summary: dict[str, Any]) -> list[str]:
    return [
        f"- commits: {summary['commit_segments']}",
        f"- drops: {summary['drop_segments']}",
        f"- mixed_script_rate: {_fmt_ratio(summary['mixed_script_rate'])}",
        f"- non_spanish_commit_rate: {_fmt_ratio(summary['non_spanish_commit_rate'])}",
        f"- hallucinated_commit_rate: {_fmt_ratio(summary['hallucinated_commit_rate'])}",
        f"- one_word_commit_rate: {_fmt_ratio(summary['one_word_commit_rate'])}",
        f"- avg_source_confidence: {summary['avg_source_confidence']:.3f}",
        f"- avg_semantic_drift: {summary['avg_semantic_drift']:.3f}",
        f"- top_root_cause: {summary['top_root_cause']}",
    ]


def _write_md(path: Path, current: dict[str, Any], baseline: dict[str, Any] | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# BUG-23 Diagnostic",
        "",
        "## Definición operativa",
        "- BUG-23 ocurre cuando el commit final mezcla idiomas/scripts, deriva semánticamente o publica texto no confiable para target `Spanish`.",
        "- `hallucinated_commit_rate` aquí cuenta solo commits finales inseguros por pureza/deriva del texto final: `mixed_script`, `non_target_language`, `translation_too_similar_to_source` o `semantic_drift_score > 0.30`.",
        "",
        "## Baseline actual",
        *(_summary_lines(current)),
        "",
        "## Hotspots",
    ]
    for cause, count in current["cause_counter"].most_common():
        lines.append(f"- {cause}: {count}")
    probable = current["top_root_cause"]
    lines.extend(
        [
            "",
            "## Causa raíz probable",
            f"- Predomina `{probable}` en el fixture analizado.",
            "- Si domina `stt_or_merge`, el drift nace antes de traducir: source fragmentado, mezclado o incompleto.",
            "- Si domina `translation`, el source llega razonable pero la salida final rompe pureza de idioma o se parece demasiado al inglés.",
            "- Si domina `commit_guard_gap`, el texto intermedio todavía no es seguro y el commit se publica demasiado pronto.",
            "",
            "## Fixes propuestos",
            "- reforzar `source_confidence` antes del commit final",
            "- bloquear commits demasiado parecidos al source cuando target es español",
            "- seguir trazando `source_text_raw -> source_text_sanitized -> translation_commit` por segmento",
        ]
    )
    if baseline is not None:
        lines.extend(
            [
                "",
                "## Antes / Después",
                f"- baseline commits: {baseline['commit_segments']}",
                f"- current commits: {current['commit_segments']}",
                f"- baseline drops: {baseline['drop_segments']}",
                f"- current drops: {current['drop_segments']}",
                f"- baseline hallucinated_commit_rate: {_fmt_ratio(baseline['hallucinated_commit_rate'])}",
                f"- current hallucinated_commit_rate: {_fmt_ratio(current['hallucinated_commit_rate'])}",
                f"- baseline non_spanish_commit_rate: {_fmt_ratio(baseline['non_spanish_commit_rate'])}",
                f"- current non_spanish_commit_rate: {_fmt_ratio(current['non_spanish_commit_rate'])}",
                f"- baseline avg_source_confidence: {baseline['avg_source_confidence']:.3f}",
                f"- current avg_source_confidence: {current['avg_source_confidence']:.3f}",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a BUG-23 diagnosis from replay events.")
    parser.add_argument("--replay-jsonl", default="./reports/replay_events.jsonl", help="Replay events JSONL path")
    parser.add_argument("--fixture-id", default="", help="Optional fixture filter")
    parser.add_argument("--output-csv", default="./reports/bug23_report.csv", help="Detailed CSV output path")
    parser.add_argument("--output-md", default="./docs/bug23_diagnostic.md", help="Markdown report path")
    parser.add_argument("--baseline-jsonl", default="", help="Optional baseline replay JSONL for before/after section")
    args = parser.parse_args()

    current_events = _load_events(Path(args.replay_jsonl).resolve())
    current_summary = _summarize(current_events, args.fixture_id.strip())
    baseline_summary = None
    if args.baseline_jsonl.strip():
        baseline_events = _load_events(Path(args.baseline_jsonl).resolve())
        baseline_summary = _summarize(baseline_events, args.fixture_id.strip())

    _write_csv(Path(args.output_csv).resolve(), current_summary["detail_rows"])
    _write_md(Path(args.output_md).resolve(), current_summary, baseline_summary)
    print(f"BUG-23 report written to {Path(args.output_md).resolve()}")
    print(f"BUG-23 CSV written to {Path(args.output_csv).resolve()}")
    for line in _summary_lines(current_summary):
        print(line[2:])


if __name__ == "__main__":
    main()
