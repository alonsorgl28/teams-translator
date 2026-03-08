#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a faster-whisper ASR baseline for a replay fixture.")
    parser.add_argument("--audio", required=True, help="Path to WAV/MP3 fixture audio")
    parser.add_argument("--output-jsonl", default="./reports/faster_whisper_segments.jsonl", help="JSONL output path")
    parser.add_argument("--output-csv", default="./reports/faster_whisper_segments.csv", help="CSV output path")
    parser.add_argument("--model", default="small", help="faster-whisper model name")
    parser.add_argument("--language", default="en", help="Language hint")
    parser.add_argument("--device", default="cpu", help="Device for faster-whisper")
    parser.add_argument("--compute-type", default="int8", help="Compute type for faster-whisper")
    parser.add_argument("--beam-size", type=int, default=1, help="Beam size")
    parser.add_argument("--vad-filter", action="store_true", help="Enable VAD filter")
    args = parser.parse_args()

    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception as exc:
        raise SystemExit(
            "Missing dependency: faster-whisper. Install it in the project venv, for example:\n"
            "  ./.venv/bin/pip install faster-whisper\n"
            f"Import error: {exc}"
        ) from exc

    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    segments, info = model.transcribe(
        args.audio,
        language=args.language,
        beam_size=args.beam_size,
        vad_filter=args.vad_filter,
        word_timestamps=True,
        condition_on_previous_text=False,
    )

    jsonl_path = Path(args.output_jsonl).resolve()
    csv_path = Path(args.output_csv).resolve()
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for idx, segment in enumerate(segments, start=1):
            text = (segment.text or "").strip()
            row = {
                "segment_id": str(idx),
                "start_s": f"{float(segment.start):.3f}",
                "end_s": f"{float(segment.end):.3f}",
                "text": text,
                "language": info.language or args.language,
                "language_probability": f"{float(info.language_probability or 0.0):.3f}",
            }
            rows.append(row)
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["segment_id", "start_s", "end_s", "language", "language_probability", "text"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"faster-whisper baseline written to {jsonl_path}")
    print(f"csv={csv_path}")


if __name__ == "__main__":
    main()
