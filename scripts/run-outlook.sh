#!/usr/bin/env bash
# Use the repo venv on Git Bash (avoids WindowsApps "python" stub).
#   ./scripts/run-outlook.sh -m robo_lukas.outlook search "read:no" --limit 5 --show-index 0 --format json
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${ROOT}/.venv/Scripts/python.exe"
if [[ ! -f "$PY" ]]; then
  echo "No venv at: $PY" >&2
  echo "Run: py -3.13 -m venv .venv && source .venv/Scripts/activate && pip install -e ." >&2
  exit 2
fi
exec "$PY" "$@"
