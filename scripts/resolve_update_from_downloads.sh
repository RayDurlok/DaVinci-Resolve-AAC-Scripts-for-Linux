#!/usr/bin/env bash
set -euo pipefail

DOWNLOAD_DIR="$HOME/Downloads"
TMP_ROOT="${TMPDIR:-/tmp}"
ZIP_PATH=""
SKIP_PACKAGE_CHECK=1
ASSUME_YES=0
REFRESH_LAUNCHER=1

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Find a DaVinci Resolve Linux ZIP in Downloads, extract it to /tmp, and run the
official installer with the Fedora-friendly package check bypass.
Close Resolve first. Installed Native AAC components are removed before the
update and reapplied afterwards if the new version is supported.

Options:
  --zip PATH                 Use this ZIP instead of auto-detecting one.
  --downloads DIR           Search this downloads folder. Default: ~/Downloads
  --tmp-dir DIR             Extract below this folder. Default: \${TMPDIR:-/tmp}
  --strict-package-check     Do not set SKIP_PACKAGE_CHECK=1.
  --no-launcher-refresh      Do not refresh the local Resolve start-menu wrapper.
  -y, --yes                 Confirm the update and native AAC maintenance plan.
  -h, --help                Show this help.
EOF
}

die() {
  echo "Error: $*" >&2
  exit 1
}

version_from_zip() {
  local base
  base="$(basename "$1")"
  if [[ "$base" =~ ^DaVinci_Resolve(_Studio)?_([0-9]+([.][0-9]+)*)_Linux[.]zip$ ]]; then
    echo "${BASH_REMATCH[2]}"
    return 0
  fi
  return 1
}

is_studio_zip() {
  [[ "$(basename "$1")" == DaVinci_Resolve_Studio_*_Linux.zip ]]
}

version_is_newer() {
  local candidate="$1"
  local current="$2"
  local newest
  newest="$(printf '%s\n%s\n' "$current" "$candidate" | sort -V | tail -n 1)"
  [[ "$newest" == "$candidate" && "$candidate" != "$current" ]]
}

mtime() {
  stat -c '%Y' "$1"
}

script_dir() {
  cd "$(dirname "${BASH_SOURCE[0]}")" && pwd
}

refresh_resolve_launcher() {
  local app_dir bin_dir apps_dir wrapper desktop
  app_dir="$(script_dir)"
  bin_dir="$HOME/.local/bin"
  apps_dir="$HOME/.local/share/applications"
  wrapper="$bin_dir/resolve-with-fonts"
  desktop="$apps_dir/com.blackmagicdesign.resolve.desktop"

  [[ -x "$app_dir/resolve-with-fonts.sh" ]] || {
    echo "Skipping launcher refresh: $app_dir/resolve-with-fonts.sh was not found or is not executable."
    return 0
  }

  mkdir -p "$bin_dir" "$apps_dir"

  cat > "$wrapper" <<EOF
#!/usr/bin/env bash
exec bash "$app_dir/resolve-with-fonts.sh" "\$@"
EOF
  chmod +x "$wrapper"

  cat > "$desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=DaVinci Resolve
GenericName=DaVinci Resolve
Comment=Revolutionary new tools for editing, visual effects, color correction and professional audio post production, all in a single application!
Path=/opt/resolve/
Exec=$wrapper %u
Terminal=false
MimeType=application/x-resolveproj;
Icon=/opt/resolve/graphics/DV_Resolve.png
StartupNotify=true
Name[en_US]=DaVinci Resolve
EOF

  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$apps_dir" >/dev/null 2>&1 || true
  fi
  if command -v kbuildsycoca6 >/dev/null 2>&1; then
    kbuildsycoca6 >/dev/null 2>&1 || true
  fi

  echo "Refreshed Resolve launcher:"
  echo "  $wrapper"
  echo "  $desktop"
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --zip=*)
      ZIP_PATH="${1#*=}"
      ;;
    --zip)
      shift || die "--zip needs a path"
      ZIP_PATH="${1:-}"
      [[ -n "$ZIP_PATH" ]] || die "--zip needs a path"
      ;;
    --downloads=*)
      DOWNLOAD_DIR="${1#*=}"
      ;;
    --downloads)
      shift || die "--downloads needs a directory"
      DOWNLOAD_DIR="${1:-}"
      [[ -n "$DOWNLOAD_DIR" ]] || die "--downloads needs a directory"
      ;;
    --tmp-dir=*)
      TMP_ROOT="${1#*=}"
      ;;
    --tmp-dir)
      shift || die "--tmp-dir needs a directory"
      TMP_ROOT="${1:-}"
      [[ -n "$TMP_ROOT" ]] || die "--tmp-dir needs a directory"
      ;;
    --strict-package-check)
      SKIP_PACKAGE_CHECK=0
      ;;
    --no-launcher-refresh)
      REFRESH_LAUNCHER=0
      ;;
    -y|--yes)
      ASSUME_YES=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown option: $1"
      ;;
  esac
  shift
done

command -v unzip >/dev/null 2>&1 || die "unzip is required."
command -v sudo >/dev/null 2>&1 || die "sudo is required."
command -v sort >/dev/null 2>&1 || die "sort is required."
command -v python3 >/dev/null 2>&1 || die "python3 is required."

if [[ -z "$ZIP_PATH" ]]; then
  [[ -d "$DOWNLOAD_DIR" ]] || die "Downloads folder not found: $DOWNLOAD_DIR"

  best_zip=""
  best_version=""

  while IFS= read -r -d '' candidate; do
    candidate_version="$(version_from_zip "$candidate" || true)"
    [[ -n "$candidate_version" ]] || continue

    if [[ -z "$best_zip" ]]; then
      best_zip="$candidate"
      best_version="$candidate_version"
    elif version_is_newer "$candidate_version" "$best_version"; then
      best_zip="$candidate"
      best_version="$candidate_version"
    elif [[ "$candidate_version" == "$best_version" ]]; then
      if is_studio_zip "$candidate" && ! is_studio_zip "$best_zip"; then
        best_zip="$candidate"
      elif is_studio_zip "$best_zip" && ! is_studio_zip "$candidate"; then
        :
      elif [[ "$(mtime "$candidate")" -gt "$(mtime "$best_zip")" ]]; then
        best_zip="$candidate"
      fi
    fi
  done < <(find "$DOWNLOAD_DIR" -maxdepth 2 -type f -name 'DaVinci_Resolve*_Linux.zip' -print0)

  [[ -n "$best_zip" ]] || die "No DaVinci Resolve Linux ZIP found below $DOWNLOAD_DIR"
  ZIP_PATH="$best_zip"
fi

[[ -f "$ZIP_PATH" ]] || die "ZIP not found: $ZIP_PATH"
VERSION="$(version_from_zip "$ZIP_PATH" || true)"
[[ -n "$VERSION" ]] || die "ZIP name does not look like a DaVinci Resolve Linux release: $ZIP_PATH"

mkdir -p "$TMP_ROOT"
WORK_DIR="$(mktemp -d "$TMP_ROOT/resolve-$VERSION.XXXXXXXX")"

echo "Resolve ZIP: $ZIP_PATH"
echo "Version:     $VERSION"
echo "Work dir:    $WORK_DIR"
echo

echo "Extracting installer..."
unzip -o "$ZIP_PATH" -d "$WORK_DIR"

mapfile -t run_files < <(find "$WORK_DIR" -maxdepth 1 -type f -name '*.run' | sort)
[[ "${#run_files[@]}" -eq 1 ]] || die "Expected exactly one .run installer in $WORK_DIR, found ${#run_files[@]}."

RUN_FILE="${run_files[0]}"
chmod +x "$RUN_FILE"

echo
echo "Installer: $RUN_FILE"
if [[ "$SKIP_PACKAGE_CHECK" -eq 1 ]]; then
  echo "Package check: bypassed with SKIP_PACKAGE_CHECK=1"
else
  echo "Package check: strict"
fi

edition=free
if is_studio_zip "$ZIP_PATH"; then edition=studio; fi
update_args=(--installer "$RUN_FILE" --version "$VERSION" --edition "$edition")
if [[ "$ASSUME_YES" -eq 1 ]]; then update_args+=(--yes); fi
if [[ "$SKIP_PACKAGE_CHECK" -eq 0 ]]; then update_args+=(--strict-package-check); fi
if python3 "$(script_dir)/resolve_aac_update.py" "${update_args[@]}"; then
  :
else
  result=$?
  if [[ "$result" -eq 20 ]]; then exit 0; fi
  exit "$result"
fi

echo
if [[ "$REFRESH_LAUNCHER" -eq 1 ]]; then
  refresh_resolve_launcher
  echo
fi

echo "Updater finished. Review the Native AAC result above before starting Resolve."
