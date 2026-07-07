#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
RESOLVE_SCRIPTS_DIR="$HOME/.local/share/DaVinciResolve/Fusion/Scripts/Edit"
RESOLVE_AAC_SCRIPTS_DIR="$RESOLVE_SCRIPTS_DIR/Resolve AAC Tools"
ASSUME_YES=0
SKIP_DEPS=0

for arg in "$@"; do
  case "$arg" in
    -y|--yes)
      ASSUME_YES=1
      ;;
    --no-deps)
      SKIP_DEPS=1
      ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Usage: $0 [--yes] [--no-deps]" >&2
      exit 2
      ;;
  esac
done

prompt_yes_no() {
  local question="$1"
  if [ "$ASSUME_YES" -eq 1 ]; then
    return 0
  fi
  if [ ! -t 0 ]; then
    return 1
  fi
  read -r -p "$question [y/N] " answer
  case "$answer" in
    y|Y|yes|YES)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

install_required_deps() {
  # python3-gobject (gi) drives the native portal "Save as" dialog; kdialog is the fallback.
  if command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3 ffmpeg python3-gobject kdialog
  elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y python3 ffmpeg python3-gi kdialog
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --needed python ffmpeg python-gobject kdialog
  elif command -v zypper >/dev/null 2>&1; then
    sudo zypper install -y python3 ffmpeg python3-gobject kdialog
  else
    echo "Could not detect a supported package manager."
    echo "Please install python3, ffmpeg, ffprobe, python3-gobject (gi), and kdialog manually."
    return 1
  fi
}

install_pyside6() {
  if command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3-pyside6
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --needed pyside6
  elif command -v zypper >/dev/null 2>&1; then
    sudo zypper install -y python3-pyside6
  else
    echo "Automatic PySide6 installation is not configured for this distro."
    echo "Install PySide6 manually, then run this installer again."
    echo "Package examples: Fedora/openSUSE: python3-pyside6, Arch: pyside6."
    return 1
  fi
}

check_dependencies() {
  if [ "$SKIP_DEPS" -eq 1 ]; then
    return 0
  fi

  missing_required=()
  for command in python3 ffmpeg ffprobe; do
    if ! command -v "$command" >/dev/null 2>&1; then
      missing_required+=("$command")
    fi
  done

  if [ "${#missing_required[@]}" -gt 0 ]; then
    echo "Missing required dependencies: ${missing_required[*]}"
    if prompt_yes_no "Install required dependencies now?"; then
      install_required_deps
    else
      echo "Please install missing dependencies before using the tools."
    fi
  fi

  if [ -x /opt/resolve/bin/resolve ]; then
    :
  else
    echo "Warning: /opt/resolve/bin/resolve was not found."
    echo "Install DaVinci Resolve or adjust the launcher script if Resolve is elsewhere."
  fi

  if command -v python3 >/dev/null 2>&1; then
    if ! python3 -c "import PySide6" >/dev/null 2>&1; then
      echo "Missing tray app dependency: PySide6"
      echo "PySide6 is required for the main tray app. CLI and Resolve menu scripts are fallback tools only."
      if prompt_yes_no "Install PySide6 now?"; then
        install_pyside6 || true
      else
        echo "Skipping PySide6. The main tray app will not start until PySide6 is installed."
      fi
    fi
  fi
}

check_dependencies

mkdir -p "$BIN_DIR" "$APPS_DIR" "$RESOLVE_AAC_SCRIPTS_DIR" "$HOME/Resolve AAC Inbox" "$HOME/Resolve AAC Imports"

cat > "$BIN_DIR/resolve-aac-import" <<EOF
#!/usr/bin/env bash
exec python3 "$APP_DIR/resolve_aac_import.py" --overwrite --import "\$@"
EOF
chmod +x "$BIN_DIR/resolve-aac-import"

cat > "$BIN_DIR/resolve-aac-watch" <<EOF
#!/usr/bin/env bash
exec python3 "$APP_DIR/resolve_aac_watch.py" "\$@"
EOF
chmod +x "$BIN_DIR/resolve-aac-watch"

cat > "$BIN_DIR/resolve-aac-current-clip" <<EOF
#!/usr/bin/env bash
exec python3 "$APP_DIR/resolve_aac_timeline.py" --overwrite "\$@"
EOF
chmod +x "$BIN_DIR/resolve-aac-current-clip"

cat > "$BIN_DIR/resolve-aac-timeline-watch" <<EOF
#!/usr/bin/env bash
exec python3 "$APP_DIR/resolve_aac_timeline_watch.py" "\$@"
EOF
chmod +x "$BIN_DIR/resolve-aac-timeline-watch"

cat > "$BIN_DIR/resolve-aac-timeline-watch-stop" <<EOF
#!/usr/bin/env bash
exec python3 "$APP_DIR/resolve_aac_timeline_watch_stop.py" "\$@"
EOF
chmod +x "$BIN_DIR/resolve-aac-timeline-watch-stop"

cat > "$BIN_DIR/resolve-aac-mediapool-watch" <<EOF
#!/usr/bin/env bash
exec python3 "$APP_DIR/resolve_aac_mediapool_watch.py" "\$@"
EOF
chmod +x "$BIN_DIR/resolve-aac-mediapool-watch"

cat > "$BIN_DIR/resolve-aac-mediapool-watch-stop" <<EOF
#!/usr/bin/env bash
exec python3 "$APP_DIR/resolve_aac_mediapool_watch_stop.py" "\$@"
EOF
chmod +x "$BIN_DIR/resolve-aac-mediapool-watch-stop"

cat > "$BIN_DIR/resolve-aac-export-watch" <<EOF
#!/usr/bin/env bash
exec python3 "$APP_DIR/resolve_aac_export_watch.py" "\$@"
EOF
chmod +x "$BIN_DIR/resolve-aac-export-watch"

cat > "$BIN_DIR/resolve-with-aac-mediapool-watch" <<EOF
#!/usr/bin/env bash
exec bash "$APP_DIR/resolve-with-aac-mediapool-watch.sh" "\$@"
EOF
chmod +x "$BIN_DIR/resolve-with-aac-mediapool-watch"

cat > "$BIN_DIR/resolve-with-fonts" <<EOF
#!/usr/bin/env bash
exec bash "$APP_DIR/resolve-with-fonts.sh" "\$@"
EOF
chmod +x "$BIN_DIR/resolve-with-fonts"

cat > "$BIN_DIR/resolve-update-from-downloads" <<EOF
#!/usr/bin/env bash
exec bash "$APP_DIR/resolve_update_from_downloads.sh" "\$@"
EOF
chmod +x "$BIN_DIR/resolve-update-from-downloads"

cat > "$BIN_DIR/resolve-aac-tray" <<EOF
#!/usr/bin/env bash
set -euo pipefail

LOG="\${RESOLVE_AAC_TRAY_LOG:-/tmp/resolve_aac_tray.log}"

if pgrep -u "\$(id -u)" -f 'python.*resolve_aac_tray.py' >/dev/null 2>&1; then
  exit 0
fi

setsid "$APP_DIR/resolve_aac_tray.py" "\$@" >>"\$LOG" 2>&1 </dev/null &
disown || true
EOF
chmod +x "$BIN_DIR/resolve-aac-tray"

cat > "$BIN_DIR/resolve-aac-start" <<EOF
#!/usr/bin/env bash
set -euo pipefail

if pgrep -u "\$(id -u)" -f 'python.*resolve_aac_tray.py' >/dev/null 2>&1; then
  mkdir -p "\$HOME/.config/resolve-aac-tools"
  : > "\$HOME/.config/resolve-aac-tools/start_resolve.request"
  exit 0
fi

LOG="\${RESOLVE_AAC_TRAY_LOG:-/tmp/resolve_aac_tray.log}"
setsid "$APP_DIR/resolve_aac_tray.py" --start-resolve "\$@" >>"\$LOG" 2>&1 </dev/null &
disown || true
EOF
chmod +x "$BIN_DIR/resolve-aac-start"

rm -f \
  "$RESOLVE_SCRIPTS_DIR/Resolve AAC Current Clip.py" \
  "$RESOLVE_SCRIPTS_DIR/Resolve AAC Timeline Watch.py" \
  "$RESOLVE_SCRIPTS_DIR/Stop Resolve AAC Timeline Watch.py" \
  "$RESOLVE_SCRIPTS_DIR/Resolve AAC MediaPool Watch.py" \
  "$RESOLVE_SCRIPTS_DIR/Stop Resolve AAC MediaPool Watch.py"

ln -sf "$APP_DIR/resolve_aac_timeline.py" "$RESOLVE_AAC_SCRIPTS_DIR/Resolve AAC Current Clip.py"
ln -sf "$APP_DIR/resolve_aac_timeline_watch.py" "$RESOLVE_AAC_SCRIPTS_DIR/Resolve AAC Timeline Watch.py"
ln -sf "$APP_DIR/resolve_aac_timeline_watch_stop.py" "$RESOLVE_AAC_SCRIPTS_DIR/Stop Resolve AAC Timeline Watch.py"
ln -sf "$APP_DIR/resolve_aac_mediapool_watch.py" "$RESOLVE_AAC_SCRIPTS_DIR/Resolve AAC MediaPool Watch.py"
ln -sf "$APP_DIR/resolve_aac_mediapool_watch_stop.py" "$RESOLVE_AAC_SCRIPTS_DIR/Stop Resolve AAC MediaPool Watch.py"

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

cat > "$APPS_DIR/resolve-aac-tray.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Resolve AAC Tools
Comment=Configure and start Resolve AAC watchers from the system tray
Exec=$BIN_DIR/resolve-aac-tray
Terminal=false
Categories=AudioVideo;Video;
EOF

cat > "$APPS_DIR/resolve-aac-start.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DaVinci Resolve AAC
Comment=Start DaVinci Resolve with the AAC MediaPool watcher and tray controls
Exec=$BIN_DIR/resolve-aac-start
Terminal=false
Categories=AudioVideo;Video;
EOF

cat > "$APPS_DIR/resolve-update-from-downloads.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DaVinci Resolve Updater
Comment=Find the newest DaVinci Resolve Linux ZIP in Downloads and run the official installer
Exec=$APP_DIR/resolve_update_from_downloads.sh
Icon=DaVinci-Resolve
Terminal=true
Categories=Utility;
Keywords=DaVinci;Resolve;Update;Installer;Blackmagic;
EOF

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi

echo "Installed:"
echo "  $APP_DIR/uninstall_user_tools.sh"
echo "  $BIN_DIR/resolve-aac-import"
echo "  $BIN_DIR/resolve-aac-watch"
echo "  $BIN_DIR/resolve-aac-current-clip"
echo "  $BIN_DIR/resolve-aac-timeline-watch"
echo "  $BIN_DIR/resolve-aac-timeline-watch-stop"
echo "  $BIN_DIR/resolve-aac-mediapool-watch"
echo "  $BIN_DIR/resolve-aac-mediapool-watch-stop"
echo "  $BIN_DIR/resolve-with-aac-mediapool-watch"
echo "  $BIN_DIR/resolve-with-fonts"
echo "  $BIN_DIR/resolve-update-from-downloads"
echo "  $BIN_DIR/resolve-aac-tray"
echo "  $BIN_DIR/resolve-aac-start"
echo "  $RESOLVE_AAC_SCRIPTS_DIR/Resolve AAC Current Clip.py"
echo "  $RESOLVE_AAC_SCRIPTS_DIR/Resolve AAC Timeline Watch.py"
echo "  $RESOLVE_AAC_SCRIPTS_DIR/Stop Resolve AAC Timeline Watch.py"
echo "  $RESOLVE_AAC_SCRIPTS_DIR/Resolve AAC MediaPool Watch.py"
echo "  $RESOLVE_AAC_SCRIPTS_DIR/Stop Resolve AAC MediaPool Watch.py"
echo "  $APPS_DIR/resolve-aac-importer.desktop"
echo "  $APPS_DIR/resolve-aac-watcher.desktop"
echo "  $APPS_DIR/resolve-with-aac-mediapool-watch.desktop"
echo "  $APPS_DIR/resolve-with-aac-mediapool-cache.desktop"
echo "  $APPS_DIR/resolve-aac-tray.desktop"
echo "  $APPS_DIR/resolve-aac-start.desktop"
echo "  $APPS_DIR/resolve-update-from-downloads.desktop"
echo
echo "Inbox:  $HOME/Resolve AAC Inbox"
echo "Output: $HOME/Resolve AAC Imports"

# Start the tray so the freshly installed tools are ready to use. If one is
# already running (i.e. this is an update), stop it and its watchers first so the
# new code is loaded before it starts again.
if pgrep -u "$(id -u)" -f 'python.*resolve_aac_tray.py' >/dev/null 2>&1; then
  echo
  echo "Restarting the running Resolve AAC tray to apply the update..."
  pkill -u "$(id -u)" -f 'python.*resolve_aac_tray.py' 2>/dev/null || true
  for _watcher in resolve_aac_export_watch resolve_aac_mediapool_watch resolve_render_location_watch; do
    pkill -u "$(id -u)" -f "python.*${_watcher}.py" 2>/dev/null || true
  done
  for _ in 1 2 3 4 5; do
    pgrep -u "$(id -u)" -f 'python.*resolve_aac_tray.py' >/dev/null 2>&1 || break
    sleep 1
  done
else
  echo
  echo "Starting the Resolve AAC tray..."
fi
"$BIN_DIR/resolve-aac-tray" >/dev/null 2>&1 || true
echo "Tray is running (resolve-aac-tray)."
