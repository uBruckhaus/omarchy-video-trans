#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
runtime_python="${XDG_DATA_HOME:-$HOME/.local/share}/video-trans/runtime/bin/python"
if [[ ! -x "$runtime_python" ]]; then
  notify-send 'Video Trans: setup needed' "Run bash $source_dir/setup.sh" || true
  exit 1
fi
exec "$runtime_python" "$source_dir/gui.py"
