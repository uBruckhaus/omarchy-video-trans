#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
runtime_python="${XDG_DATA_HOME:-$HOME/.local/share}/video-trans/runtime/bin/python"
if [[ ! -x "$runtime_python" ]]; then
  # Before setup: the standard-library parts (status, setup, settings) run on the system Python.
  runtime_python=python3
fi
exec "$runtime_python" "$source_dir/bridge.py" "$@"
