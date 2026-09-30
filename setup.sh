#!/usr/bin/env bash
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
runtime_dir="${XDG_DATA_HOME:-$HOME/.local/share}/video-trans/runtime"
for dependency in ffmpeg pactl; do
  command -v "$dependency" >/dev/null || { echo "Missing $dependency. Install with: omarchy pkg add ffmpeg libpulse" >&2; exit 1; }
done
if command -v uv >/dev/null; then
  if [[ ! -x "$runtime_dir/bin/python" ]]; then
    uv venv --python 3.12 "$runtime_dir"
  fi
  uv pip install --python "$runtime_dir/bin/python" -r "$source_dir/requirements.lock"
else
  echo 'uv is needed to create an isolated Python 3.12 runtime. Install with: omarchy pkg add uv' >&2
  exit 1
fi
echo 'Video Trans runtime ready. Whisper downloads the selected speech model on first Start.'
