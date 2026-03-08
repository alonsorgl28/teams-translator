#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from replay_tools import load_replay_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch Loro against a local replay fixture WAV.")
    parser.add_argument("--fixture-id", required=True, help="Fixture ID from replay manifest")
    parser.add_argument(
        "--manifest",
        default="./bench/replay_manifest.yaml",
        help="Path to replay manifest YAML",
    )
    parser.add_argument(
        "--source-language",
        default="English",
        help="Source language for replay session",
    )
    parser.add_argument(
        "--target-language",
        default="Spanish",
        help="Target language for replay session",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Do not auto-exit after replay fixture completes",
    )
    parser.add_argument(
        "qt_args",
        nargs="*",
        help="Optional extra args passed through to run.sh/main.py",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    fixtures = load_replay_manifest(manifest_path)
    fixture = fixtures.get(args.fixture_id)
    if fixture is None:
        raise SystemExit(f"Fixture not found in manifest: {args.fixture_id}")
    if not fixture.audio_path:
        raise SystemExit(f"Fixture {args.fixture_id} has no audio_path in manifest")

    audio_path = Path(fixture.audio_path)
    if not audio_path.exists():
        raise SystemExit(f"Fixture audio not found: {audio_path}")

    env = dict(os.environ)
    env["REPLAY_AUDIO_PATH"] = str(audio_path)
    env["REPLAY_FIXTURE_ID"] = fixture.fixture_id
    env["REPLAY_MANIFEST_PATH"] = str(manifest_path)
    env["REPLAY_AUTO_START"] = "1"
    env["REPLAY_AUTO_STOP_ON_COMPLETE"] = "1"
    env["REPLAY_AUTO_EXIT_ON_COMPLETE"] = "0" if args.keep_open else "1"
    env["BENCHMARK_TEST_ID"] = fixture.fixture_id
    env["SOURCE_LANGUAGE"] = args.source_language
    env["TARGET_LANGUAGE"] = args.target_language

    command = [str(ROOT / "run.sh"), *args.qt_args]
    subprocess.run(command, cwd=str(ROOT), env=env, check=True)


if __name__ == "__main__":
    main()
