#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
RESOLVE_SCRIPTS_DIR="$HOME/.local/share/DaVinciResolve/Fusion/Scripts/Edit"

mkdir -p "$BIN_DIR" "$APPS_DIR" "$RESOLVE_SCRIPTS_DIR" "$HOME/Resolve AAC Inbox" "$HOME/Resolve AAC Imports"

cat > "$BIN_DIR/resolve-aac-import" <<EOF
#!/usr/bin/env bash
exec "$APP_DIR/resolve_aac_import.py" --overwrite --import "\$@"
EOF
chmod +x "$BIN_DIR/resolve-aac-import"

cat > "$BIN_DIR/resolve-aac-watch" <<EOF
#!/usr/bin/env bash
exec "$APP_DIR/resolve_aac_watch.py" "\$@"
EOF
chmod +x "$BIN_DIR/resolve-aac-watch"

cat > "$BIN_DIR/resolve-aac-current-clip" <<EOF
#!/usr/bin/env bash
exec "$APP_DIR/resolve_aac_timeline.py" --overwrite "\$@"
EOF
chmod +x "$BIN_DIR/resolve-aac-current-clip"

cat > "$BIN_DIR/resolve-aac-timeline-watch" <<EOF
#!/usr/bin/env bash
exec "$APP_DIR/resolve_aac_timeline_watch.py" "\$@"
EOF
chmod +x "$BIN_DIR/resolve-aac-timeline-watch"

cat > "$BIN_DIR/resolve-aac-timeline-watch-stop" <<EOF
#!/usr/bin/env bash
exec "$APP_DIR/resolve_aac_timeline_watch_stop.py" "\$@"
EOF
chmod +x "$BIN_DIR/resolve-aac-timeline-watch-stop"

cat > "$BIN_DIR/resolve-aac-mediapool-watch" <<EOF
#!/usr/bin/env bash
exec "$APP_DIR/resolve_aac_mediapool_watch.py" "\$@"
EOF
chmod +x "$BIN_DIR/resolve-aac-mediapool-watch"

cat > "$BIN_DIR/resolve-aac-mediapool-watch-stop" <<EOF
#!/usr/bin/env bash
exec "$APP_DIR/resolve_aac_mediapool_watch_stop.py" "\$@"
EOF
chmod +x "$BIN_DIR/resolve-aac-mediapool-watch-stop"

cat > "$BIN_DIR/resolve-with-aac-mediapool-watch" <<EOF
#!/usr/bin/env bash
exec "$APP_DIR/resolve-with-aac-mediapool-watch.sh" "\$@"
EOF
chmod +x "$BIN_DIR/resolve-with-aac-mediapool-watch"

ln -sf "$APP_DIR/resolve_aac_timeline.py" "$RESOLVE_SCRIPTS_DIR/Resolve AAC Current Clip.py"
ln -sf "$APP_DIR/resolve_aac_timeline_watch.py" "$RESOLVE_SCRIPTS_DIR/Resolve AAC Timeline Watch.py"
ln -sf "$APP_DIR/resolve_aac_timeline_watch_stop.py" "$RESOLVE_SCRIPTS_DIR/Stop Resolve AAC Timeline Watch.py"
ln -sf "$APP_DIR/resolve_aac_mediapool_watch.py" "$RESOLVE_SCRIPTS_DIR/Resolve AAC MediaPool Watch.py"
ln -sf "$APP_DIR/resolve_aac_mediapool_watch_stop.py" "$RESOLVE_SCRIPTS_DIR/Stop Resolve AAC MediaPool Watch.py"

cat > "$APPS_DIR/resolve-aac-importer.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Resolve AAC Importer
Comment=Convert AAC media to Resolve-friendly MOV/PCM and import into Resolve
Exec=$BIN_DIR/resolve-aac-import %F
Terminal=true
Categories=AudioVideo;Video;
MimeType=video/mp4;video/quicktime;audio/mp4;audio/aac;audio/x-aac;video/x-matroska;
EOF

cat > "$APPS_DIR/resolve-aac-watcher.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Resolve AAC Watch Folder
Comment=Watch ~/Resolve AAC Inbox and import converted AAC media into Resolve
Exec=$BIN_DIR/resolve-aac-watch
Terminal=true
Categories=AudioVideo;Video;
EOF

cat > "$APPS_DIR/resolve-with-aac-mediapool-watch.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DaVinci Resolve AAC Watch
Comment=Start DaVinci Resolve and an AAC MediaPool replacement watcher
Exec=$BIN_DIR/resolve-with-aac-mediapool-watch
Terminal=false
Categories=AudioVideo;Video;
EOF

cat > "$APPS_DIR/resolve-with-aac-mediapool-cache.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DaVinci Resolve AAC Watch Cached
Comment=Start DaVinci Resolve and store AAC remuxes outside source folders
Exec=env RESOLVE_AAC_CACHE_DIR=$HOME/.cache/resolve-aac-remux $BIN_DIR/resolve-with-aac-mediapool-watch
Terminal=false
Categories=AudioVideo;Video;
EOF

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi

echo "Installed:"
echo "  $BIN_DIR/resolve-aac-import"
echo "  $BIN_DIR/resolve-aac-watch"
echo "  $BIN_DIR/resolve-aac-current-clip"
echo "  $BIN_DIR/resolve-aac-timeline-watch"
echo "  $BIN_DIR/resolve-aac-timeline-watch-stop"
echo "  $BIN_DIR/resolve-aac-mediapool-watch"
echo "  $BIN_DIR/resolve-aac-mediapool-watch-stop"
echo "  $BIN_DIR/resolve-with-aac-mediapool-watch"
echo "  $RESOLVE_SCRIPTS_DIR/Resolve AAC Current Clip.py"
echo "  $RESOLVE_SCRIPTS_DIR/Resolve AAC Timeline Watch.py"
echo "  $RESOLVE_SCRIPTS_DIR/Stop Resolve AAC Timeline Watch.py"
echo "  $RESOLVE_SCRIPTS_DIR/Resolve AAC MediaPool Watch.py"
echo "  $RESOLVE_SCRIPTS_DIR/Stop Resolve AAC MediaPool Watch.py"
echo "  $APPS_DIR/resolve-aac-importer.desktop"
echo "  $APPS_DIR/resolve-aac-watcher.desktop"
echo "  $APPS_DIR/resolve-with-aac-mediapool-watch.desktop"
echo "  $APPS_DIR/resolve-with-aac-mediapool-cache.desktop"
echo
echo "Inbox:  $HOME/Resolve AAC Inbox"
echo "Output: $HOME/Resolve AAC Imports"
