#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="/opt/resolve/IOPlugins/aac_codec_probe_plugin.dvcp.bundle"
DISABLED_DIR="/opt/resolve/IOPlugins/aac_codec_probe_plugin.dvcp.bundle.disabled"

if [ -d "$PLUGIN_DIR" ]; then
  echo "Probe plugin is already enabled:"
  echo "  $PLUGIN_DIR"
  exit 0
fi

if [ ! -d "$DISABLED_DIR" ]; then
  echo "Disabled probe plugin was not found:"
  echo "  $DISABLED_DIR"
  exit 0
fi

sudo mv "$DISABLED_DIR" "$PLUGIN_DIR"
echo "Enabled probe plugin:"
echo "  $PLUGIN_DIR"
