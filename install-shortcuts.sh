#!/usr/bin/env bash
# Command and desktop actions for shortcuts (Launch & Bind: Apps → Video Trans → Shortcuts).
# Files without the managed marker belong to someone else and are left alone.
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
marker='# Managed by ubruckhaus.video-trans'
bin_dir="$HOME/.local/bin"
apps_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
launcher="$bin_dir/video-trans"
desktop="$apps_dir/video-trans.desktop"
mkdir -p "$bin_dir" "$apps_dir"
if [[ ! -e "$launcher" && ! -L "$launcher" ]] || { [[ -f "$launcher" && ! -L "$launcher" ]] && grep -qxF "$marker" "$launcher"; }; then
  printf '#!/usr/bin/env bash\n%s\nexec bash %q "$@"\n' "$marker" "$source_dir/bridge.sh" > "$launcher.tmp"
  chmod 755 "$launcher.tmp"
  mv -f "$launcher.tmp" "$launcher"
else
  echo "Kept existing $launcher (not managed by Video Trans); desktop actions need the video-trans command."
fi
if [[ ! -e "$desktop" && ! -L "$desktop" ]] || { [[ -f "$desktop" && ! -L "$desktop" ]] && grep -qxF 'X-Video-Trans-Managed=true' "$desktop"; }; then
  install -m 644 "$source_dir/video-trans.desktop" "$desktop.tmp"
  mv -f "$desktop.tmp" "$desktop"
else
  echo "Kept existing $desktop (not managed by Video Trans)."
fi
