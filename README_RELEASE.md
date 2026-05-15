AAC Codec Probe Plugin for DaVinci Resolve (Linux)
==================================================

This archive contains:
- aac_codec_probe_plugin.dvcp.bundle/ (plugin bundle folder)
- install.sh (installer script)
- README.txt (this file)

How to install:
---------------
Run the installer. The plugin will be installed to /opt/resolve/IOPlugins:
   ./install.sh

Or you can manually copy aac_codec_probe_plugin.dvcp.bundle folder to /opt/resolve/IOPlugins


Requirements:
-------------
- DaVinci Resolve Studio (FREE does NOT support plugins!)
- FFmpeg

After installation, restart DaVinci Resolve.

This build keeps the AAC encoder and adds a decoder probe that logs Resolve decoder callbacks. It does not output decoded PCM yet.
