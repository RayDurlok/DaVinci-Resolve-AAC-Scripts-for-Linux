#!/usr/bin/env bash
set -euo pipefail

BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
AUTOSTART_PATH="$HOME/.config/autostart/resolve-aac-tray.desktop"
CONFIG_DIR="$HOME/.config/resolve-aac-tools"
RESOLVE_SCRIPTS_DIR="$HOME/.local/share/DaVinciResolve/Fusion/Scripts/Edit"
RESOLVE_AAC_SCRIPTS_DIR="$RESOLVE_SCRIPTS_DIR/Resolve AAC Tools"
FUSION_PREFS_PATH="$HOME/.local/share/DaVinciResolve/Fusion/Profiles/Default/Fusion.prefs"
DEFAULT_CACHE_DIR="$HOME/.cache/resolve-aac-remux"
KEEP_AUTOSTART=0
KEEP_CONFIG=0
REMOVE_CACHE=0

for arg in "$@"; do
  case "$arg" in
    --keep-autostart)
      KEEP_AUTOSTART=1
      ;;
    --keep-config)
      KEEP_CONFIG=1
      ;;
    --remove-cache)
      REMOVE_CACHE=1
      ;;
    -h|--help)
      echo "Usage: $0 [--keep-autostart] [--keep-config] [--remove-cache]"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Usage: $0 [--keep-autostart] [--keep-config] [--remove-cache]" >&2
      exit 2
      ;;
  esac
done

rm -f \
  "$BIN_DIR/resolve-aac-import" \
  "$BIN_DIR/resolve-aac-watch" \
  "$BIN_DIR/resolve-aac-current-clip" \
  "$BIN_DIR/resolve-aac-timeline-watch" \
  "$BIN_DIR/resolve-aac-timeline-watch-stop" \
  "$BIN_DIR/resolve-aac-mediapool-watch" \
  "$BIN_DIR/resolve-aac-mediapool-watch-stop" \
  "$BIN_DIR/resolve-aac-export-watch" \
  "$BIN_DIR/resolve-with-aac-mediapool-watch" \
  "$BIN_DIR/resolve-with-fonts" \
  "$BIN_DIR/resolve-aac-tray" \
  "$BIN_DIR/resolve-aac-start" \
  "$APPS_DIR/resolve-aac-importer.desktop" \
  "$APPS_DIR/resolve-aac-watcher.desktop" \
  "$APPS_DIR/resolve-with-aac-mediapool-watch.desktop" \
  "$APPS_DIR/resolve-with-aac-mediapool-cache.desktop" \
  "$APPS_DIR/resolve-aac-tray.desktop" \
  "$APPS_DIR/resolve-aac-start.desktop" \
  "$RESOLVE_SCRIPTS_DIR/Resolve AAC Current Clip.py" \
  "$RESOLVE_SCRIPTS_DIR/Resolve AAC Timeline Watch.py" \
  "$RESOLVE_SCRIPTS_DIR/Stop Resolve AAC Timeline Watch.py" \
  "$RESOLVE_SCRIPTS_DIR/Resolve AAC MediaPool Watch.py" \
  "$RESOLVE_SCRIPTS_DIR/Stop Resolve AAC MediaPool Watch.py"

rm -rf "$RESOLVE_AAC_SCRIPTS_DIR"

if [ "$KEEP_AUTOSTART" -eq 0 ]; then
  rm -f "$AUTOSTART_PATH"
fi

if [ "$KEEP_CONFIG" -eq 0 ]; then
  rm -rf "$CONFIG_DIR"
fi

if [ "$REMOVE_CACHE" -eq 1 ]; then
  rm -rf "$DEFAULT_CACHE_DIR"
fi

RESOLVE_DESKTOP_OVERRIDE="$APPS_DIR/com.blackmagicdesign.resolve.desktop"
if [ -f "$RESOLVE_DESKTOP_OVERRIDE" ] && grep -Fq "$BIN_DIR/resolve-with-fonts" "$RESOLVE_DESKTOP_OVERRIDE"; then
  rm -f "$RESOLVE_DESKTOP_OVERRIDE"
fi

if [ -f "$FUSION_PREFS_PATH" ]; then
  perl -0pi -e 's/\["SystemFonts:"\] = "\$\(FUSION_FONTS\);[^"]*",/["SystemFonts:"] = "$(FUSION_FONTS)",/g' "$FUSION_PREFS_PATH"
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi

if command -v kbuildsycoca6 >/dev/null 2>&1; then
  kbuildsycoca6 >/dev/null 2>&1 || true
fi

echo "Resolve AAC Tools uninstalled."
if [ "$REMOVE_CACHE" -eq 0 ]; then
  echo "Cache kept: $DEFAULT_CACHE_DIR"
  echo "Use --remove-cache if you also want to delete cached remux files."
fi
