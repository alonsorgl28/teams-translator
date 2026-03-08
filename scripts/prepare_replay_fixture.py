#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from replay_tools import FixtureSpec, load_replay_manifest


def _require_binary(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise SystemExit(
            f"Missing dependency: {name}. Install it first. On macOS: `brew install {name}`"
        )
    return found


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=str(cwd), check=True)


def _pick_first(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _resolve_caption_fixture(fixture: FixtureSpec, out_dir: Path) -> Path:
    if fixture.reference_caption_path:
        return Path(fixture.reference_caption_path)
    return out_dir / "reference.en.vtt"


def _resolve_audio_fixture(fixture: FixtureSpec, out_dir: Path) -> Path:
    if fixture.audio_path:
        return Path(fixture.audio_path)
    return out_dir / "fixture.wav"


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and normalize a replay fixture for Loro.")
    parser.add_argument("--fixture-id", required=True, help="Fixture ID from replay manifest")
    parser.add_argument(
        "--manifest",
        default="./bench/replay_manifest.yaml",
        help="Path to replay manifest YAML",
    )
    parser.add_argument(
        "--out-root",
        default="./output/replay",
        help="Root directory for downloaded fixture artifacts",
    )
    parser.add_argument(
        "--transcribe-reference",
        action="store_true",
        help="Generate a reference transcript via the transcribe skill CLI if available",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    fixtures = load_replay_manifest(manifest_path)
    fixture = fixtures.get(args.fixture_id)
    if fixture is None:
        raise SystemExit(f"Fixture not found in manifest: {args.fixture_id}")
    if not fixture.source_url or fixture.source_url == "N/D":
        raise SystemExit(f"Fixture {args.fixture_id} has no source_url in manifest")

    yt_dlp = _require_binary("yt-dlp")
    ffmpeg = _require_binary("ffmpeg")

    out_root = Path(args.out_root).resolve()
    out_dir = out_root / fixture.fixture_id
    out_dir.mkdir(parents=True, exist_ok=True)
    download_template = str(out_dir / "source.%(ext)s")

    _run(
        [
            yt_dlp,
            "--no-playlist",
            "-f",
            "bestaudio/best",
            "-o",
            download_template,
            fixture.source_url,
        ],
        cwd=ROOT,
    )
    _run(
        [
            yt_dlp,
            "--skip-download",
            "--write-auto-sub",
            "--write-sub",
            "--sub-format",
            "vtt",
            "--sub-langs",
            "en,en-US,en-GB",
            "-o",
            download_template,
            fixture.source_url,
        ],
        cwd=ROOT,
    )

    downloaded_media = _pick_first(
        [
            out_dir / "source.m4a",
            out_dir / "source.webm",
            out_dir / "source.mp4",
            out_dir / "source.mp3",
        ]
    )
    if downloaded_media is None:
        raise SystemExit(f"No media file downloaded under {out_dir}")

    output_audio = _resolve_audio_fixture(fixture, out_dir)
    output_audio.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_cmd = [
        ffmpeg,
        "-y",
        "-ss",
        f"{fixture.clip_start_s:.3f}",
        "-t",
        f"{fixture.duration_s:.3f}",
        "-i",
        str(downloaded_media),
        "-ac",
        "1",
        "-ar",
        "16000",
        str(output_audio),
    ]
    _run(ffmpeg_cmd, cwd=ROOT)

    downloaded_caption = _pick_first(sorted(out_dir.glob("source*.en*.vtt")))
    output_caption = _resolve_caption_fixture(fixture, out_dir)
    if downloaded_caption is not None:
        output_caption.parent.mkdir(parents=True, exist_ok=True)
        if downloaded_caption.resolve() != output_caption.resolve():
            shutil.copyfile(downloaded_caption, output_caption)

    if args.transcribe_reference:
        transcribe_cli = os.getenv("TRANSCRIBE_CLI") or os.path.expanduser(
            "~/.codex/skills/transcribe/scripts/transcribe_diarize.py"
        )
        transcript_path = Path(fixture.reference_transcript_path) if fixture.reference_transcript_path else out_dir / "reference.txt"
        if Path(transcribe_cli).exists():
            transcript_path.parent.mkdir(parents=True, exist_ok=True)
            _run(
                [
                    sys.executable,
                    transcribe_cli,
                    str(output_audio),
                    "--response-format",
                    "text",
                    "--out",
                    str(transcript_path),
                ],
                cwd=ROOT,
            )
        else:
            print(f"TRANSCRIBE_CLI not found at {transcribe_cli}; skipped reference transcript")

    print(f"Fixture ready: {fixture.fixture_id}")
    print(f"audio={output_audio}")
    print(f"captions={output_caption if output_caption.exists() else 'N/D'}")


if __name__ == "__main__":
    main()
