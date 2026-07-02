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

preload_system_glib_if_needed() {
  local resolve_glib="/opt/resolve/libs/libglib-2.0.so.0"
  local system_glib="/lib64/libglib-2.0.so.0"
  local preload_libs=()

  if [[ -r "$resolve_glib" && -r "$system_glib" ]] &&
     ! readelf -Ws "$resolve_glib" 2>/dev/null | grep -q 'g_once_init_leave_pointer'; then
    for lib in \
      /lib64/libglib-2.0.so.0 \
      /lib64/libgobject-2.0.so.0 \
      /lib64/libgio-2.0.so.0 \
      /lib64/libgmodule-2.0.so.0; do
      [[ -r "$lib" ]] && preload_libs+=("$lib")
    done
  fi

  if [[ "${#preload_libs[@]}" -gt 0 ]]; then
    export LD_PRELOAD="${preload_libs[*]}${LD_PRELOAD:+ $LD_PRELOAD}"
  fi
}

preload_system_glib_if_needed

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
