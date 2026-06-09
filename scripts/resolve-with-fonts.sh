#!/usr/bin/env bash
set -euo pipefail

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

# Native KDE-Dateidialoge (Speichern/Export/Import) statt Resolves altem Qt-Widget-Dialog.
# Resolve bringt kein platformthemes-Plugin mit -> wir stellen das System-Plugin
# (libqxdgdesktopportal.so, leitet QFileDialog an xdg-desktop-portal-kde) bereit.
# Nur dieses eine Plugin liegt im Pfad, daher keine Kollision mit Resolves Qt-Plugins.
RESOLVE_QT_PLUGINS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/qt-plugins"
if [[ -e "$RESOLVE_QT_PLUGINS/platformthemes/libqxdgdesktopportal.so" ]]; then
  export QT_QPA_PLATFORMTHEME=xdgdesktopportal
  export QT_PLUGIN_PATH="$RESOLVE_QT_PLUGINS${QT_PLUGIN_PATH:+:$QT_PLUGIN_PATH}"
fi

exec /opt/resolve/bin/resolve "$@"
