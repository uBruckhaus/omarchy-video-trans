#!/usr/bin/env bash
# Started by the bar widget. Without the runtime there is no tray yet; the widget retries.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
runtime_python="${XDG_DATA_HOME:-$HOME/.local/share}/video-trans/runtime/bin/python"
[[ -x "$runtime_python" ]] || exit 0
exec "$runtime_python" "$source_dir/tray.py"
