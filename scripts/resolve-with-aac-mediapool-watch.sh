#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="/tmp/resolve_aac_launcher.log"
STOP="/tmp/resolve_aac_mediapool_watch.stop"
WATCH_INTERVAL="${RESOLVE_AAC_WATCH_INTERVAL:-5}"
WATCH_DELAY="${RESOLVE_AAC_WATCH_DELAY:-15}"
WATCH_ARGS=(--interval "$WATCH_INTERVAL" --quiet)

if [[ -n "${RESOLVE_AAC_CACHE_DIR:-}" ]]; then
  WATCH_ARGS+=(--cache-dir "$RESOLVE_AAC_CACHE_DIR")
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
