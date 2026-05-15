#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AAC_LIB_DIR="$ROOT_DIR/ffmpeg-resolve-aac/lib"

export LD_LIBRARY_PATH="$AAC_LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export LD_PRELOAD="$AAC_LIB_DIR/libavcodec.so.60:$AAC_LIB_DIR/libavformat.so.60:$AAC_LIB_DIR/libavutil.so.58:$AAC_LIB_DIR/libswscale.so.7${LD_PRELOAD:+:$LD_PRELOAD}"
exec /opt/resolve/bin/resolve "$@"
