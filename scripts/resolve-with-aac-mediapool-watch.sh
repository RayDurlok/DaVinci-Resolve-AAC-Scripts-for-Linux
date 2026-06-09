#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="/tmp/resolve_aac_launcher.log"
STOP="/tmp/resolve_aac_mediapool_watch.stop"
WATCH_INTERVAL="${RESOLVE_AAC_WATCH_INTERVAL:-5}"
WATCH_DELAY="${RESOLVE_AAC_WATCH_DELAY:-15}"
WATCH_ARGS=(--interval "$WATCH_INTERVAL" --quiet)
FONT_WRAPPER="$HOME/.local/bin/resolve-with-fonts"
RESOLVE_DESKTOP="$HOME/.local/share/applications/com.blackmagicdesign.resolve.desktop"

if [[ "${RESOLVE_FONT_FIX:-0}" == "1" ]] || {
  [[ -x "$FONT_WRAPPER" ]] &&
  [[ -f "$RESOLVE_DESKTOP" ]] &&
  grep -Fq "Exec=$FONT_WRAPPER" "$RESOLVE_DESKTOP"
}; then
  FONT_DIRS="/usr/share/fonts;/usr/local/share/fonts"

  if [[ -d /usr/local/share/fonts ]]; then
    while IFS= read -r font_dir; do
      FONT_DIRS+=";$font_dir"
    done < <(find /usr/local/share/fonts -mindepth 1 -maxdepth 1 -type d | sort)
  fi

  if [[ -d "$HOME/.local/share/fonts" ]]; then
    FONT_DIRS+=";$HOME/.local/share/fonts"
  fi

  if [[ -d "$HOME/.fonts" ]]; then
    FONT_DIRS+=";$HOME/.fonts"
  fi

  export FUSION_FONTS="${FUSION_FONTS:+$FUSION_FONTS;}$FONT_DIRS"
fi

if [[ -n "${RESOLVE_AAC_CACHE_DIR:-}" ]]; then
  WATCH_ARGS+=(--cache-dir "$RESOLVE_AAC_CACHE_DIR")
fi

# Native KDE-Dateidialoge statt Resolves altem Qt-Widget-Dialog (siehe resolve-with-fonts.sh).
RESOLVE_QT_PLUGINS="$(cd "$APP_DIR/.." && pwd)/qt-plugins"
if [[ -e "$RESOLVE_QT_PLUGINS/platformthemes/libqxdgdesktopportal.so" ]]; then
  export QT_QPA_PLATFORMTHEME=xdgdesktopportal
  export QT_PLUGIN_PATH="$RESOLVE_QT_PLUGINS${QT_PLUGIN_PATH:+:$QT_PLUGIN_PATH}"
fi

rm -f "$STOP"

/opt/resolve/bin/resolve "$@" &
resolve_pid=$!

(
  sleep "$WATCH_DELAY"
  "$APP_DIR/resolve_aac_mediapool_watch.py" "${WATCH_ARGS[@]}" >>"$LOG" 2>&1
) &
watcher_pid=$!

resolve_status=0
wait "$resolve_pid" || resolve_status=$?

touch "$STOP"
wait "$watcher_pid" || true

exit "$resolve_status"
