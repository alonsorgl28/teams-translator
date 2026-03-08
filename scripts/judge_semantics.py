#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
from pathlib import Path

JUDGE_PROMPT = """You are a strict EN->ES subtitle evaluator.
Score adequacy from 1.0 to 5.0 using:
1 = wrong meaning, 2 = major omissions/errors, 3 = understandable with errors,
4 = mostly correct with minor drift, 5 = faithful and fluent.
Return ONLY a JSON object: {"score": <float>, "critical_error": <true|false>, "reason": "<short>"}."""


def _sanitize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\wáéíóúüñÁÉÍÓÚÜÑ]+\b", text or ""))


def _contains_disallowed_script(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u0400-\u052F\u0590-\u05FF\u0600-\u06FF\u0750-\u077F]", text or ""))


def _heuristic_score(source_text: str, translated_text: str) -> tuple[float, bool, str]:
    source = _sanitize(source_text)
    target = _sanitize(translated_text)
    if not source or not target:
        return 1.5, True, "empty"
    src_words = _word_count(source)
    tgt_words = _word_count(target)
    if tgt_words == 0:
        return 1.5, True, "no_target_words"
    ratio = tgt_words / max(1, src_words)
    ratio_penalty = min(1.2, abs(1.0 - ratio))
    script_penalty = 1.3 if _contains_disallowed_script(target) else 0.0
    english_hits = len(re.findall(r"\b(the|and|or|with|for|to|of|in|on|is|are|was|were)\b", target.lower()))
    spanish_hits = len(re.findall(r"\b(el|la|los|las|de|del|y|con|para|en|que|es|un|una|por)\b", target.lower()))
    language_penalty = 0.9 if english_hits >= (spanish_hits * 2 + 2) else 0.0
    base = 4.6
    if tgt_words <= 2:
        base -= 1.0
    score = base - ratio_penalty - script_penalty - language_penalty
    score = max(1.0, min(5.0, score))
    critical = script_penalty > 0 or language_penalty > 0 or score < 2.8
    if critical and script_penalty > 0:
        reason = "script_mismatch"
    elif critical and language_penalty > 0:
        reason = "language_mixture"
    elif critical:
        reason = "low_adequacy"
    else:
        reason = "ok"
    return score, critical, reason


def _judge_with_openai(model: str, source_text: str, translated_text: str) -> tuple[float, bool, str]:
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    prompt = (
        f"{JUDGE_PROMPT}\n\n"
        f"Source:\n{source_text}\n\n"
        f"Translated:\n{translated_text}\n"
    )
    response = client.chat.completions.create(
        model=model,
        temperature=0.0,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=120,
    )
    content = response.choices[0].message.content or "{}"
    try:
        data = json.loads(content)
        score = float(data.get("score", 3.0))
        critical = bool(data.get("critical_error", False))
        reason = str(data.get("reason", ""))
        return max(1.0, min(5.0, score)), critical, reason
    except Exception:
        return _heuristic_score(source_text, translated_text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Semantic adequacy judge for Loro segment outputs.")
    parser.add_argument(
        "--metrics-jsonl",
        default=os.getenv("METRICS_OUTPUT_PATH", "./reports/session_metrics.jsonl"),
        help="Path to session_metrics.jsonl",
    )
    parser.add_argument(
        "--output-csv",
        default="./reports/semantic_judge.csv",
        help="Output CSV path",
    )
    parser.add_argument(
        "--llm-judge",
        action="store_true",
        help="Use OpenAI model judge instead of local heuristic",
    )
    parser.add_argument(
        "--judge-model",
        default="gpt-4o-mini",
        help="Model for semantic judge when --llm-judge is enabled",
    )
    args = parser.parse_args()

    metrics_path = Path(args.metrics_jsonl)
    rows: list[dict[str, str]] = []
    if not metrics_path.exists():
        raise SystemExit(f"Metrics file not found: {metrics_path}")

    event_idx = 0
    score_values: list[float] = []
    critical_count = 0
    for line in metrics_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("event_type") != "segment":
            continue
        if str(payload.get("segment_stage", "commit")) != "commit":
            continue
        source_text = str(payload.get("source_text") or "")
        rendered_text = str(payload.get("rendered_text") or "")
        if not source_text or not rendered_text:
            continue
        event_idx += 1
        if args.llm_judge and os.getenv("OPENAI_API_KEY"):
            score, critical, reason = _judge_with_openai(args.judge_model, source_text, rendered_text)
        else:
            score, critical, reason = _heuristic_score(source_text, rendered_text)
        score_values.append(score)
        if critical:
            critical_count += 1
        rows.append(
            {
                "event_id": str(event_idx),
                "score_0_5": f"{score:.3f}",
                "critical_error": "1" if critical else "0",
                "reason": reason,
                "source_text": source_text,
                "translated_text": rendered_text,
                "route": str(payload.get("route", "normal")),
                "latency_total_s": f"{float(payload.get('latency_total_s', 0.0) or 0.0):.3f}",
            }
        )

    output_path = Path(args.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "event_id",
            "score_0_5",
            "critical_error",
            "reason",
            "route",
            "latency_total_s",
            "source_text",
            "translated_text",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    avg = (sum(score_values) / len(score_values)) if score_values else float("nan")
    critical_ratio = (critical_count / len(score_values)) if score_values else float("nan")
    avg_label = "N/D" if math.isnan(avg) else f"{avg:.3f}"
    ratio_label = "N/D" if math.isnan(critical_ratio) else f"{critical_ratio:.3f}"
    print(f"Semantic judge output: {output_path}")
    print(f"segments={len(score_values)} avg_score={avg_label} critical_ratio={ratio_label}")


if __name__ == "__main__":
    main()
