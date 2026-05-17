#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FFMPEG_VERSION="6.0"
TARBALL="$ROOT_DIR/ffmpeg-$FFMPEG_VERSION.tar.xz"
SRC_DIR="$ROOT_DIR/ffmpeg-$FFMPEG_VERSION"
PREFIX="$ROOT_DIR/ffmpeg-resolve-aac"

if [ ! -f "$TARBALL" ]; then
  curl -L "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz" -o "$TARBALL"
fi

if [ ! -d "$SRC_DIR" ]; then
  tar -xf "$TARBALL" -C "$ROOT_DIR"
fi

cd "$SRC_DIR"

if command -v clang >/dev/null 2>&1; then
  CC_BIN="clang"
else
  CC_BIN="cc"
fi

if [ -f config.mak ]; then
  make distclean
fi

./configure \
  --cc="$CC_BIN" \
  --prefix="$PREFIX" \
  --enable-runtime-cpudetect \
  --disable-lzma \
  --disable-xlib \
  --enable-shared \
  --disable-programs \
  --disable-doc \
  --disable-avdevice \
  --disable-postproc \
  --disable-avfilter \
  --disable-pixelutils \
  --disable-static \
  --disable-swresample \
  --disable-iconv \
  --disable-asm \
  --disable-x86asm

make -j"$(nproc)"
make install

cat > "$ROOT_DIR/resolve-with-aac.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
AAC_LIB_DIR="\$ROOT_DIR/ffmpeg-resolve-aac/lib"

export LD_LIBRARY_PATH="\$AAC_LIB_DIR\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
export LD_PRELOAD="\$AAC_LIB_DIR/libavcodec.so.60:\$AAC_LIB_DIR/libavformat.so.60:\$AAC_LIB_DIR/libavutil.so.58:\$AAC_LIB_DIR/libswscale.so.7\${LD_PRELOAD:+:\$LD_PRELOAD}"
exec /opt/resolve/bin/resolve "\$@"
EOF
chmod +x "$ROOT_DIR/resolve-with-aac.sh"

echo "Built FFmpeg $FFMPEG_VERSION with AAC enabled:"
echo "  $PREFIX/lib"
echo
echo "Launcher:"
echo "  $ROOT_DIR/resolve-with-aac.sh"
