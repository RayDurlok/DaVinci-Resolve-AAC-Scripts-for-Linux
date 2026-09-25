#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
    install-patch) step=import ;;
    install-export) step=export ;;
    uninstall) step=restore ;;
    run-installer) step=update ;;
    *) echo "Unknown native AAC operation" >&2; exit 2 ;;
esac
printf 'NATIVE_AAC_PROGRESS {"step":"%s","state":"running","message":"Administrator approval received. Applying changes."}\n' "$step"

# This check runs AFTER the authentication prompt, not only before it opens.
root=/opt/resolve
bundle="$root/IOPlugins/aac_ffmpeg6_experiment.dvcp.bundle"
for entry in /proc/[0-9]*/exe; do
    executable=$(readlink "$entry" 2>/dev/null || true)
    if [[ "$executable" == "$root/bin/resolve" || "$executable" == "$root/bin/resolve (deleted)" ]]; then
        echo "Close Resolve first. Refusing to modify a running installation." >&2
        exit 1
    fi
done

if [[ "${1:-}" == run-installer ]]; then
    [[ -f "${2:-}" && "$2" == *.run ]] || { echo "Resolve installer missing." >&2; exit 1; }
    if [[ -e "$root/bin/resolve.aac-orig" || -e "$root/bin/.resolve.aac-orig.sha256" ||
          -e "$root/libs/_bmd_orig" || -e "$bundle" ]]; then
        echo "Native AAC files/backups remain. Refusing to run the Resolve installer." >&2
        exit 1
    fi
    if [[ "${3:-}" == 1 ]]; then
        exec env SKIP_PACKAGE_CHECK=1 "$2" -i
    else
        exec env -u SKIP_PACKAGE_CHECK "$2" -i
    fi
fi

# Never mix a saved binary from one Resolve build with another installed build.
if [[ -f "$root/bin/resolve.aac-orig" ]]; then
    python3 - "$root/bin/resolve" "$root/bin/resolve.aac-orig" <<'PY'
import mmap
import re
import sys
def marker(path):
    with open(path, "rb") as file, mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as data:
        match = re.search(rb"\b\d+\.\d+\.\d+\.\d+_(?:studio|free)\b", data)
        if not match:
            raise SystemExit("Cannot identify Resolve backup build; refusing to modify it.")
        return match[0]
if marker(sys.argv[1]) != marker(sys.argv[2]):
    raise SystemExit("Resolve and its AAC backup are from different builds. Refusing stale-backup restore/patch; reinstall a clean matching Resolve first.")
PY
fi

case "${1:-}" in
    install-patch)
        exec bash "$2/aac-fix" install "$root"
        ;;
    install-export)
        destination="$bundle/Contents/Linux-x86-64/aac_ffmpeg6_experiment.dvcp"
        install -D -m 755 -- "$2" "$destination.new"
        mv -f -- "$destination.new" "$destination"
        ;;
    uninstall)
        if [[ -e "$bundle" ]]; then
            # Keep a unique disabled backup so repeated install/undo cycles work.
            backup=$(mktemp -d "$root/IOPlugins/aac-export-disabled.XXXXXXXX")
            mv -T -- "$bundle" "$backup/bundle.disabled"
        fi
        exec bash "$2/aac-fix" uninstall "$root"
        ;;
    *) echo "Unknown native AAC operation" >&2; exit 2 ;;
esac
