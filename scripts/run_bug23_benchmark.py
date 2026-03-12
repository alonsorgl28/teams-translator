#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the BUG-23 replay benchmark pipeline.")
    parser.add_argument("--fixture-id", required=True, help="Fixture ID from bench/replay_manifest.yaml")
    parser.add_argument("--manifest", default="./bench/replay_manifest.yaml", help="Replay manifest path")
    parser.add_argument("--report-md", default="./docs/bug23_diagnostic.md", help="BUG-23 markdown report path")
    parser.add_argument("--report-csv", default="./reports/bug23_report.csv", help="BUG-23 detailed CSV output path")
    parser.add_argument("--replay-jsonl", default="./reports/replay_events.jsonl", help="Replay events JSONL path")
    parser.add_argument("--metrics-csv", default="./reports/replay_metrics.csv", help="Replay metrics CSV path")
    parser.add_argument("--diff-csv", default="./reports/replay_diff.csv", help="Replay diff CSV path")
    parser.add_argument("--baseline-jsonl", default="", help="Optional baseline replay JSONL to compare against")
    args = parser.parse_args()

    _run(
        [
            sys.executable,
            "scripts/run_replay_session.py",
            "--fixture-id",
            args.fixture_id,
            "--manifest",
            args.manifest,
        ]
    )
    _run(
        [
            sys.executable,
            "scripts/replay_compare.py",
            "--fixture-id",
            args.fixture_id,
            "--manifest",
            args.manifest,
            "--replay-jsonl",
            args.replay_jsonl,
            "--output-csv",
            args.diff_csv,
        ]
    )
    _run(
        [
            sys.executable,
            "scripts/replay_metrics.py",
            "--fixture-id",
            args.fixture_id,
            "--replay-jsonl",
            args.replay_jsonl,
            "--output-csv",
            args.metrics_csv,
        ]
    )
    command = [
        sys.executable,
        "scripts/bug23_report.py",
        "--fixture-id",
        args.fixture_id,
        "--replay-jsonl",
        args.replay_jsonl,
        "--output-md",
        args.report_md,
        "--output-csv",
        args.report_csv,
    ]
    if args.baseline_jsonl:
        command.extend(["--baseline-jsonl", args.baseline_jsonl])
    _run(command)


if __name__ == "__main__":
    main()
