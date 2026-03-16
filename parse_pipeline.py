#!/usr/bin/env python3
"""
parse_pipeline.py — Analiza session_metrics.jsonl y muestra breakdown por etapa.

Uso:
    python parse_pipeline.py                          # usa ./reports/session_metrics.jsonl
    python parse_pipeline.py reports/otro.jsonl       # archivo personalizado
    python parse_pipeline.py --compare file_a file_b  # compara dos sesiones (ej: VAD off vs on)
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean, median, quantiles


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _delta_s(start: str, end: str) -> float:
    return max(0.0, (_ts(end) - _ts(start)).total_seconds())


def _pct(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    return quantiles(values, n=100)[p - 1]


def _fmt(v: float) -> str:
    return f"{v:.3f}s"


def load_records(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def analyze(path: Path, label: str = "") -> dict:
    """Analiza un archivo JSONL y devuelve métricas + imprime reporte."""
    records = load_records(path)
    header = f"=== Loro Pipeline Analysis{' — ' + label if label else ''} ==="
    print(f"\n{header}")
    print(f"Archivo  : {path}")

    if not records:
        print("Sin datos.")
        return {}

    commit_segs  = [r for r in records if r.get("segment_stage") == "commit"]
    preview_segs = [r for r in records if r.get("segment_stage") == "preview"]
    drop_segs    = [r for r in records if r.get("segment_stage") == "drop"]

    print(f"Registros: {len(records)} total  |  {len(commit_segs)} commit  |  {len(preview_segs)} preview  |  {len(drop_segs)} drop")

    if not commit_segs:
        print("Sin segmentos commit — nothing to analyze.")
        return {}

    # --- Tiempo al primer subtítulo ---
    render_ts = [r.get("render_t", 0.0) for r in commit_segs if r.get("render_t") is not None]
    first_subtitle_s = min(render_ts) if render_ts else None

    # --- Breakdown por etapa ---
    pre_api_list     = []
    stt_list         = []
    queue_wait_list  = []
    translation_list = []
    total_list       = []

    for r in commit_segs:
        try:
            pre_api_list.append(_delta_s(r["captured_at"], r["transcription_start"]))
            stt_list.append(float(r.get("transcription_time_s", 0.0)))
            queue_wait_list.append(_delta_s(r["transcription_end"], r["translation_start"]))
            translation_list.append(float(r.get("translation_time_s", 0.0)))
            total_list.append(float(r.get("latency_total_s", 0.0)))
        except (KeyError, TypeError, ValueError):
            continue

    def stats(values: list[float]) -> str:
        if not values:
            return "N/A"
        avg = mean(values)
        med = median(values)
        p95 = _pct(values, 95)
        return f"avg={_fmt(avg)}  med={_fmt(med)}  p95={_fmt(p95)}  min={_fmt(min(values))}  max={_fmt(max(values))}"

    print(f"\n--- Tiempo al primer subtitulo ---")
    print(f"  first_commit_render_t : {_fmt(first_subtitle_s) if first_subtitle_s is not None else 'N/A'}")

    print(f"\n--- Breakdown por etapa (n={len(total_list)} commit segments) ---")
    print(f"  [1] Pre-API (audio→STT):    {stats(pre_api_list)}")
    print(f"  [2] STT (transcripcion):     {stats(stt_list)}")
    print(f"  [3] Queue wait (STT→transl): {stats(queue_wait_list)}")
    print(f"  [4] Traduccion:              {stats(translation_list)}")
    print(f"  [TOTAL] Latencia e2e:        {stats(total_list)}")

    if total_list and mean(total_list) > 0:
        avg_total = mean(total_list)
        print(f"\n--- Distribucion % del total (avg={_fmt(avg_total)}) ---")
        for name, lst in [("Pre-API", pre_api_list), ("STT", stt_list), ("Queue wait", queue_wait_list), ("Traduccion", translation_list)]:
            pct = (mean(lst) / avg_total * 100) if lst else 0.0
            bar = "#" * int(pct / 2)
            print(f"  {name:<12} {mean(lst):.3f}s  {pct:5.1f}%  {bar}")

    # --- Backlog ---
    audio_backlogs = [r.get("audio_backlog", 0) for r in commit_segs]
    text_backlogs  = [r.get("text_backlog", 0) for r in commit_segs]
    print(f"\n--- Backlog ---")
    print(f"  audio_backlog avg={mean(audio_backlogs):.1f}  max={max(audio_backlogs)}")
    print(f"  text_backlog  avg={mean(text_backlogs):.1f}  max={max(text_backlogs)}")

    # --- Drops ---
    if drop_segs:
        drop_reasons: dict[str, int] = {}
        for r in drop_segs:
            reason = r.get("dropped_reason") or r.get("fallback_reason") or "unknown"
            drop_reasons[reason] = drop_reasons.get(reason, 0) + 1
        print(f"\n--- Drops ({len(drop_segs)}) ---")
        for reason, count in sorted(drop_reasons.items(), key=lambda x: -x[1]):
            print(f"  {reason:<40} {count}")

    # --- Emit interval con análisis de gaps largos ---
    commits_ordered = sorted(commit_segs, key=lambda r: r.get("recorded_at", ""))
    emit_intervals = [r.get("emit_interval_s", 0.0) for r in commits_ordered if r.get("emit_interval_s", 0.0) > 0]
    if emit_intervals:
        print(f"\n--- Intervalo entre subtitulos (emit_interval) ---")
        print(f"  {stats(emit_intervals)}")
        long_gaps = [(r, r.get("emit_interval_s", 0.0)) for r in commits_ordered if r.get("emit_interval_s", 0.0) > 4.0]
        if long_gaps:
            print(f"\n  Gaps > 4s ({len(long_gaps)} casos):")
            for r, gap in long_gaps:
                ab = r.get("audio_backlog", 0)
                tb = r.get("text_backlog", 0)
                text = (r.get("rendered_text") or "")[:45]
                cause = "silencio natural" if ab == 0 and tb == 0 else f"backlog ab={ab} tb={tb}"
                print(f"    gap={gap:.1f}s  [{cause}]  \"{text}\"")

    # --- Últimos 10 commit ---
    print(f"\n--- Ultimos 10 segmentos commit ---")
    print(f"  {'#':<3}  {'latency':>8}  {'STT':>7}  {'transl':>7}  {'q_wait':>7}  texto")
    for i, r in enumerate(commit_segs[-10:], 1):
        try:
            lat  = float(r.get("latency_total_s", 0))
            stt  = float(r.get("transcription_time_s", 0))
            tr   = float(r.get("translation_time_s", 0))
            qw   = _delta_s(r["transcription_end"], r["translation_start"])
            text = (r.get("rendered_text") or "")[:55]
            print(f"  {i:<3}  {lat:>8.3f}  {stt:>7.3f}  {tr:>7.3f}  {qw:>7.3f}  {text}")
        except (KeyError, TypeError, ValueError):
            continue

    print()

    return {
        "label": label or str(path),
        "n_commit": len(commit_segs),
        "n_drop": len(drop_segs),
        "n_preview": len(preview_segs),
        "first_subtitle_s": first_subtitle_s,
        "avg_latency": mean(total_list) if total_list else 0.0,
        "p95_latency": _pct(total_list, 95) if total_list else 0.0,
        "avg_stt": mean(stt_list) if stt_list else 0.0,
        "avg_translation": mean(translation_list) if translation_list else 0.0,
        "avg_queue_wait": mean(queue_wait_list) if queue_wait_list else 0.0,
        "avg_emit_interval": mean(emit_intervals) if emit_intervals else 0.0,
        "p95_emit_interval": _pct(emit_intervals, 95) if emit_intervals else 0.0,
        "drop_rate": len(drop_segs) / max(1, len(records)),
    }


def compare(path_a: Path, path_b: Path) -> None:
    """Compara dos sesiones lado a lado (ej: VAD off vs VAD on)."""
    m_a = analyze(path_a, label=path_a.stem)
    m_b = analyze(path_b, label=path_b.stem)

    if not m_a or not m_b:
        return

    print("=" * 60)
    print("COMPARACION LADO A LADO")
    print("=" * 60)

    rows = [
        ("Segmentos commit",      "n_commit",           "",    False),
        ("Drops",                 "n_drop",             "",    False),
        ("Primer subtitulo",      "first_subtitle_s",   "s",   True),
        ("Latencia avg",          "avg_latency",        "s",   True),
        ("Latencia P95",          "p95_latency",        "s",   True),
        ("STT avg",               "avg_stt",            "s",   True),
        ("Traduccion avg",        "avg_translation",    "s",   True),
        ("Queue wait avg",        "avg_queue_wait",     "s",   True),
        ("Emit interval avg",     "avg_emit_interval",  "s",   True),
        ("Emit interval P95",     "p95_emit_interval",  "s",   True),
        ("Drop rate",             "drop_rate",          "%",   True),
    ]

    label_a = m_a["label"][:20]
    label_b = m_b["label"][:20]
    print(f"  {'Metrica':<22}  {label_a:>14}  {label_b:>14}  {'Delta':>10}")
    print(f"  {'-'*22}  {'-'*14}  {'-'*14}  {'-'*10}")

    for name, key, unit, lower_is_better in rows:
        va = m_a.get(key)
        vb = m_b.get(key)
        if va is None or vb is None:
            continue
        if unit == "%":
            sa = f"{va*100:.1f}%"
            sb = f"{vb*100:.1f}%"
            delta = (vb - va) * 100
            sd = f"{delta:+.1f}%"
        elif unit == "s":
            sa = f"{va:.3f}s"
            sb = f"{vb:.3f}s"
            delta = vb - va
            sd = f"{delta:+.3f}s"
        else:
            sa = str(int(va))
            sb = str(int(vb))
            delta = vb - va
            sd = f"{delta:+.0f}"

        marker = ""
        if unit in ("s", "%") and lower_is_better:
            if delta < -0.05 * abs(va + 1e-9):
                marker = " <mejor"
            elif delta > 0.05 * abs(va + 1e-9):
                marker = " <peor"

        print(f"  {name:<22}  {sa:>14}  {sb:>14}  {sd:>10}{marker}")

    print()


if __name__ == "__main__":
    args = sys.argv[1:]

    if args and args[0] == "--compare":
        if len(args) < 3:
            print("Uso: python parse_pipeline.py --compare archivo_a.jsonl archivo_b.jsonl")
            sys.exit(1)
        compare(Path(args[1]), Path(args[2]))
    else:
        default = Path("./reports/session_metrics.jsonl")
        target = Path(args[0]) if args else default
        if not target.exists():
            print(f"Archivo no encontrado: {target}")
            sys.exit(1)
        analyze(target)
