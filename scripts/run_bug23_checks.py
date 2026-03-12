#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VENV_BIN = ROOT / ".venv" / "bin"
RUFF_TARGETS = [
    "main.py",
    "segment_quality.py",
    "translation_service.py",
    "scripts/bug23_report.py",
    "scripts/replay_compare.py",
    "scripts/replay_metrics.py",
    "scripts/run_bug23_benchmark.py",
    "scripts/run_bug23_checks.py",
    "tests/test_bug23_properties.py",
    "tests/test_segment_quality.py",
    "tests/test_translation_service.py",
]


def _resolve_tool(name: str) -> str:
    candidate = VENV_BIN / name
    if candidate.exists():
        return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"Tool not found: {name}. Install dev dependencies with `pip install -r requirements-dev.txt`.")


def _run(command: list[str]) -> None:
    env = dict(os.environ)
    env.setdefault("RUFF_CACHE_DIR", "/tmp/loro-ruff-cache")
    env.setdefault("XDG_CACHE_HOME", "/tmp/loro-xdg-cache")
    env.setdefault("PYRIGHT_PYTHON_CACHE_DIR", "/tmp/loro-pyright-cache")
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run BUG-23 static checks and property tests.")
    parser.add_argument("--skip-ruff", action="store_true", help="Skip ruff")
    parser.add_argument("--skip-pyright", action="store_true", help="Skip pyright")
    parser.add_argument("--skip-tests", action="store_true", help="Skip unittest property suite")
    args = parser.parse_args()

    if not args.skip_ruff:
        _run([_resolve_tool("ruff"), "check", *RUFF_TARGETS, "--config", str(ROOT / "ruff.toml"), "--no-cache"])
    if not args.skip_pyright:
        _run([_resolve_tool("pyright"), "--project", str(ROOT / "pyrightconfig.json")])
    if not args.skip_tests:
        _run(
            [
                sys.executable,
                "-m",
                "unittest",
                "tests.test_bug23_properties",
                "tests.test_segment_quality",
                "tests.test_translation_service",
            ]
        )


if __name__ == "__main__":
    main()
