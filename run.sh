#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python3.11"
QT_BASE="$SCRIPT_DIR/.venv/lib/python3.11/site-packages/PyQt6/Qt6"
QT_PLATFORM_SRC="$QT_BASE/plugins/platforms"
QT_PLATFORM_STAGE="/tmp/loro-qt-platforms-${UID:-$(id -u)}"

# Work around platform plugin discovery failures from this filesystem by staging plugins to /tmp.
mkdir -p "$QT_PLATFORM_STAGE"
cp "$QT_PLATFORM_SRC"/libq*.dylib "$QT_PLATFORM_STAGE"/ 2>/dev/null

export QT_QPA_PLATFORM_PLUGIN_PATH="$QT_PLATFORM_STAGE"
export QT_PLUGIN_PATH="$QT_BASE/plugins"
export DYLD_FALLBACK_LIBRARY_PATH="$QT_BASE/lib:${DYLD_FALLBACK_LIBRARY_PATH:-}"
if [[ -z "${LANG:-}" || "${LANG}" == C* ]]; then
  export LANG="en_US.UTF-8"
fi
if [[ -z "${LC_ALL:-}" || "${LC_ALL}" == C* ]]; then
  export LC_ALL="en_US.UTF-8"
fi

exec "$VENV_PYTHON" "$SCRIPT_DIR/main.py" "$@"
