#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_LIB_DIR="$ROOT_DIR/ffmpeg-resolve-aac/lib"
RESOLVE_LIB_DIR="/opt/resolve/libs"
BACKUP_ROOT="$ROOT_DIR/resolve-lib-backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$BACKUP_ROOT/$STAMP"

LIB_PATTERNS=(
  "libavcodec.so*"
  "libavformat.so*"
  "libavutil.so*"
  "libswscale.so*"
)

REQUIRED_LIBS=(
  "$SRC_LIB_DIR/libavcodec.so.60.3.100"
  "$SRC_LIB_DIR/libavformat.so.60.3.100"
  "$SRC_LIB_DIR/libavutil.so.58.2.100"
  "$SRC_LIB_DIR/libswscale.so.7.1.100"
)

for lib in "${REQUIRED_LIBS[@]}"; do
  if [ ! -f "$lib" ]; then
    echo "Missing built library: $lib" >&2
    echo "Run ./build_resolve_ffmpeg_aac.sh first." >&2
    exit 1
  fi
done

mkdir -p "$BACKUP_DIR"

echo "Backing up Resolve FFmpeg libraries to:"
echo "  $BACKUP_DIR"
for pattern in "${LIB_PATTERNS[@]}"; do
  shopt -s nullglob
  matches=("$RESOLVE_LIB_DIR"/$pattern)
  shopt -u nullglob
  if [ "${#matches[@]}" -gt 0 ]; then
    sudo cp -a "${matches[@]}" "$BACKUP_DIR/"
  fi
done

echo "Installing AAC-enabled FFmpeg libraries into:"
echo "  $RESOLVE_LIB_DIR"
sudo cp -a \
  "$SRC_LIB_DIR"/libavcodec.so* \
  "$SRC_LIB_DIR"/libavformat.so* \
  "$SRC_LIB_DIR"/libavutil.so* \
  "$SRC_LIB_DIR"/libswscale.so* \
  "$RESOLVE_LIB_DIR/"

echo
echo "Installed. Backup kept at:"
echo "  $BACKUP_DIR"
echo
echo "To restore this backup:"
echo "  sudo cp -a \"$BACKUP_DIR\"/* \"$RESOLVE_LIB_DIR/\""
