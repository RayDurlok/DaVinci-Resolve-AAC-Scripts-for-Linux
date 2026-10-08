#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$HERE/../../native-dialogs"
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT
if [[ -n "${QT5_HEADERS:-}" ]]; then
  flags=(-I"$QT5_HEADERS" -I"$QT5_HEADERS/QtCore" -I"$QT5_HEADERS/QtGui" -I"$QT5_HEADERS/QtWidgets")
else
  read -r -a flags <<< "$(pkg-config --cflags Qt5Widgets)"
fi
if [[ -n "${RESOLVE_LIBS:-}" ]]; then
  link=(-L"$RESOLVE_LIBS" -Wl,-rpath,"$RESOLVE_LIBS" -l:libQt5Widgets.so.5 -l:libQt5Gui.so.5 -l:libQt5Core.so.5)
else
  read -r -a link <<< "$(pkg-config --libs Qt5Widgets)"
fi
moc="${QT5_MOC:-$(command -v moc || true)}"
[[ -n "$moc" ]] || moc="$(pkg-config --variable=host_bins Qt5Core)/moc"
flags+=(-std=c++17 -fPIC -pthread -DQT_NO_VERSION_TAGGING -I"$SOURCE" -I"$BUILD")
compiler="${CXX:-c++}"
"$compiler" "${flags[@]}" -shared "$SOURCE"/*.cpp "${link[@]}" -ldl -Wl,-z,defs -o "$BUILD/dialogs.so"
"$moc" "$HERE/bridge_test.cpp" -o "$BUILD/bridge_test.moc"
"$compiler" "${flags[@]}" "$HERE/bridge_test.cpp" "$SOURCE/relink_bridge.cpp" "${link[@]}" -o "$BUILD/bridge-test"
"$compiler" "${flags[@]}" "$HERE/verification_test.cpp" "$SOURCE/relink_bridge.cpp" "${link[@]}" -o "$BUILD/verification-test"
"$compiler" "${flags[@]}" "$HERE/deliver_test.cpp" "$SOURCE/deliver_bridge.cpp" "${link[@]}" -o "$BUILD/deliver-test"
"$compiler" "${flags[@]}" "$HERE/smoke_test.cpp" "${link[@]}" -o "$BUILD/smoke-test"
cp "$HERE/deliver_test_helper.py" "$BUILD/"
export QT_QPA_PLATFORM=offscreen
"$BUILD/bridge-test"
"$BUILD/verification-test"
"$BUILD/deliver-test"
RESOLVE_TOOLKIT_NATIVE_DIALOGS=1 LD_PRELOAD="${LD_PRELOAD:+$LD_PRELOAD }$BUILD/dialogs.so" "$BUILD/smoke-test"
