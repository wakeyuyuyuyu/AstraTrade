#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${1:-8787}"

is_python311() {
  "$1" - <<'PY' >/dev/null 2>&1
import sys

raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)
PY
}

if [ -n "${PYTHON:-}" ]; then
  PYTHON_BIN="$(bash scripts/ensure_python311.sh "$PYTHON")"
elif [ -x ".venv/bin/python" ] && is_python311 ".venv/bin/python"; then
  PYTHON_BIN=".venv/bin/python"
elif [ -n "${CONDA_PREFIX:-}" ] && [ -x "$CONDA_PREFIX/bin/python" ] && is_python311 "$CONDA_PREFIX/bin/python"; then
  PYTHON_BIN="$CONDA_PREFIX/bin/python"
else
  PYTHON_BIN="$(bash scripts/ensure_python311.sh)"
fi

export STOCK_AGENT_PYTHON="${STOCK_AGENT_PYTHON:-$PYTHON_BIN}"
exec "$PYTHON_BIN" dashboard/server.py "$PORT"
