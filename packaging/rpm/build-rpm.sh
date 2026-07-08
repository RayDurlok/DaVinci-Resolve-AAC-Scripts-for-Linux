#!/usr/bin/env bash
# Build the Resolve AAC Tools RPM locally.
#
#   packaging/rpm/build-rpm.sh [VERSION]
#
# Produces a source tarball with the same runtime payload as the GitHub release,
# then runs rpmbuild -ba (binary + SRPM; the SRPM is what Copr consumes later).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SRCNAME="resolve-aac-tools"
VERSION="${1:-$(rpmspec -q --qf '%{version}\n' "$HERE/$SRCNAME.spec" 2>/dev/null | head -1)}"
VERSION="${VERSION:-0.1.11}"

RPMTOP="${RPMTOP:-$HOME/rpmbuild}"
mkdir -p "$RPMTOP"/{SOURCES,SPECS,BUILD,BUILDROOT,RPMS,SRPMS,TMP}

echo ">> Building source tarball for $SRCNAME-$VERSION"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
DEST="$STAGE/$SRCNAME-$VERSION"
mkdir -p "$DEST"

# Docs
cp "$REPO/README.md" "$REPO/LICENSE" "$DEST/"

# Runtime payload (matches .github/workflows/release.yml, minus the installer scripts)
cp "$REPO"/scripts/resolve_aac_*.py "$DEST/"
cp "$REPO"/scripts/set_render_location.py "$DEST/"
cp "$REPO"/scripts/resolve_render_location_watch.py "$DEST/"
cp "$REPO"/scripts/resolve_update_from_downloads.sh "$DEST/"
cp "$REPO"/scripts/resolve-with-aac-mediapool-watch.sh "$DEST/"
cp "$REPO"/scripts/resolve-with-fonts.sh "$DEST/"

tar -C "$STAGE" -czf "$RPMTOP/SOURCES/$SRCNAME-$VERSION.tar.gz" "$SRCNAME-$VERSION"

echo ">> Staging spec + packaging sources"
cp "$HERE"/*.metainfo.xml "$HERE"/*.desktop "$RPMTOP/SOURCES/"
cp "$REPO/resolve-aac-tools-icon-512.png" "$RPMTOP/SOURCES/"
cp "$HERE/$SRCNAME.spec" "$RPMTOP/SPECS/"

# --nodeps: the BuildRequires (desktop-file-utils, libappstream-glib) are only
# used by the guarded %check validation. Copr/mock install them automatically;
# a local dev box need not. Runtime Requires are unaffected (checked at install).
echo ">> rpmbuild -ba --nodeps"
rpmbuild -ba --nodeps \
  --define "_topdir $RPMTOP" \
  --define "_tmppath $RPMTOP/TMP" \
  "$RPMTOP/SPECS/$SRCNAME.spec"

echo
echo ">> Built:"
find "$RPMTOP/RPMS" "$RPMTOP/SRPMS" -name "$SRCNAME-$VERSION-*.rpm" -newer "$HERE/$SRCNAME.spec" -o -name "$SRCNAME-$VERSION-*.rpm" | sort -u
