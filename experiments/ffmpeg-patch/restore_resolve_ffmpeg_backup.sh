#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOLVE_LIB_DIR="/opt/resolve/libs"
BACKUP_ROOT="$ROOT_DIR/resolve-lib-backups"

if [ "${1:-}" = "" ]; then
  latest="$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort | tail -n 1)"
else
  latest="$1"
fi

if [ "$latest" = "" ] || [ ! -d "$latest" ]; then
  echo "No backup directory found." >&2
  echo "Usage: $0 [backup-dir]" >&2
  exit 1
fi

echo "Restoring Resolve FFmpeg libraries from:"
echo "  $latest"
sudo cp -a "$latest"/* "$RESOLVE_LIB_DIR/"
echo "Restore complete."
