#!/usr/bin/env bash
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
runtime_python="${XDG_DATA_HOME:-$HOME/.local/share}/video-trans/runtime/bin/python"
if [[ ! -x "$runtime_python" ]]; then
  echo '{"error":"Run Video Trans setup.sh first."}'
  exit 1
fi
exec "$runtime_python" "$source_dir/bridge.py"
