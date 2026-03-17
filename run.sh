#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python3.11"
UV="/opt/homebrew/bin/uv"

# Auto-repair venv if Python or dotenv is missing (uv es más robusto que venv nativo)
if ! "$VENV_PYTHON" -c "import dotenv" 2>/dev/null; then
  echo "[Loro] venv roto — recreando con uv..."
  cd "$SCRIPT_DIR"
  "$UV" venv .venv --python 3.11 --clear
  "$UV" pip install -r requirements.txt
  echo "[Loro] venv listo"
  # Re-sign PyQt6 dylibs after fresh venv (macOS Sequoia requirement)
  PYQT6_QT6="$SCRIPT_DIR/.venv/lib/python3.11/site-packages/PyQt6/Qt6"
  if [[ -d "$PYQT6_QT6" ]]; then
    echo "[Loro] firmando plugins Qt..."
    xattr -rd com.apple.quarantine "$PYQT6_QT6" 2>/dev/null || true
    find "$PYQT6_QT6" -name "*.dylib" -exec codesign --sign - --force {} \; 2>/dev/null || true
    echo "[Loro] plugins Qt firmados"
  fi
fi

if [[ -z "${LANG:-}" || "${LANG}" == C* ]]; then
  export LANG="en_US.UTF-8"
fi
if [[ -z "${LC_ALL:-}" || "${LC_ALL}" == C* ]]; then
  export LC_ALL="en_US.UTF-8"
fi

# macOS Sequoia: set Qt plugin path before Python starts so cocoa plugin is always found
PYQT6_PLUGINS="$SCRIPT_DIR/.venv/lib/python3.11/site-packages/PyQt6/Qt6/plugins"
if [[ -d "$PYQT6_PLUGINS/platforms" ]]; then
  export QT_PLUGIN_PATH="$PYQT6_PLUGINS"
  export QT_QPA_PLATFORM_PLUGIN_PATH="$PYQT6_PLUGINS/platforms"
fi

exec "$VENV_PYTHON" "$SCRIPT_DIR/main.py" "$@"
