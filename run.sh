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
fi

if [[ -z "${LANG:-}" || "${LANG}" == C* ]]; then
  export LANG="en_US.UTF-8"
fi
if [[ -z "${LC_ALL:-}" || "${LC_ALL}" == C* ]]; then
  export LC_ALL="en_US.UTF-8"
fi

exec "$VENV_PYTHON" "$SCRIPT_DIR/main.py" "$@"
