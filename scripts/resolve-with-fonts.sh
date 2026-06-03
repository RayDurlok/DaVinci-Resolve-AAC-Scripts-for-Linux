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

exec /opt/resolve/bin/resolve "$@"
