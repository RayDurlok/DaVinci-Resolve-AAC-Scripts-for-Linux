#!/bin/bash
set -e

# Build the plugin and package it into the correct bundle structure
PLUGIN_NAME="aac_codec_probe_plugin.dvcp"
BUNDLE_NAME="aac_codec_probe_plugin.dvcp.bundle"
BUNDLE_DIR="$BUNDLE_NAME/Contents/Linux-x86-64"

# Clean previous build
rm -rf "$BUNDLE_NAME"
mkdir -p "$BUNDLE_DIR"

# Build (assumes Makefile produces $PLUGIN_NAME in current dir or bin/)
make clean && make ENABLE_ENCODER="${ENABLE_ENCODER:-0}"

# Copy the built plugin to the bundle
if [ -f "bin/$PLUGIN_NAME" ]; then
  cp "bin/$PLUGIN_NAME" "$BUNDLE_DIR/"
elif [ -f "$PLUGIN_NAME" ]; then
  cp "$PLUGIN_NAME" "$BUNDLE_DIR/"
else
  echo "Error: $PLUGIN_NAME not found after build."
  exit 1
fi

echo "Bundle created at $BUNDLE_DIR/$PLUGIN_NAME"
