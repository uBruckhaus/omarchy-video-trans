#!/usr/bin/env bash
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
runtime_dir="${XDG_DATA_HOME:-$HOME/.local/share}/video-trans/runtime"
lock="$source_dir/requirements.lock"
# Exact interpreter: uv installs this CPython build only after checking it against the
# SHA256 it ships for that download.
python_version=3.12.14
for dependency in ffmpeg pactl quickshell; do
  command -v "$dependency" >/dev/null || { echo "Missing $dependency. Install with: omarchy pkg add ffmpeg libpulse quickshell" >&2; exit 1; }
done
command -v uv >/dev/null || { echo 'uv is needed to create an isolated Python 3.12 runtime. Install with: omarchy pkg add uv' >&2; exit 1; }

want="$(sha256sum "$lock" | cut -d' ' -f1)"
have="$(cat "$runtime_dir/.verified-lock" 2>/dev/null || true)"
if [[ "$have" != "$want" ]]; then
  # A runtime not verified against this lock is made again, never upgraded in place.
  rm -rf -- "$runtime_dir"
  uv venv --python "$python_version" --no-config "$runtime_dir"
  # Exactly the lock's files (sha256 checked), wheels only, nothing else installed.
  uv pip sync --python "$runtime_dir/bin/python" --no-config --require-hashes --only-binary :all: --reinstall "$lock"
  printf '%s\n' "$want" > "$runtime_dir/.verified-lock"
fi

bash "$source_dir/install-shortcuts.sh"
echo 'Video Trans runtime ready. Whisper downloads the selected speech model on first Start.'
