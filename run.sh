#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python3.11"
QT_BASE="$SCRIPT_DIR/.venv/lib/python3.11/site-packages/PyQt6/Qt6"

export QT_QPA_PLATFORM_PLUGIN_PATH="$QT_BASE/plugins/platforms"
export DYLD_FALLBACK_LIBRARY_PATH="$QT_BASE/lib:${DYLD_FALLBACK_LIBRARY_PATH:-}"

exec "$VENV_PYTHON" "$SCRIPT_DIR/main.py" "$@"
