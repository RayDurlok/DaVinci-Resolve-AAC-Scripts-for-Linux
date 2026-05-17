#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="/opt/resolve/IOPlugins/aac_codec_probe_plugin.dvcp.bundle"
DISABLED_DIR="/opt/resolve/IOPlugins/aac_codec_probe_plugin.dvcp.bundle.disabled"

if [ -d "$DISABLED_DIR" ]; then
  echo "Probe plugin is already disabled:"
  echo "  $DISABLED_DIR"
  exit 0
fi

if [ ! -d "$PLUGIN_DIR" ]; then
  echo "Probe plugin was not found:"
  echo "  $PLUGIN_DIR"
  exit 0
fi

sudo mv "$PLUGIN_DIR" "$DISABLED_DIR"
echo "Disabled probe plugin:"
echo "  $DISABLED_DIR"
