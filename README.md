# DaVinci Resolve AAC Tools for Linux

Inspired by: https://github.com/jchai01/davinci-resolve-aac-workaround-macro

A small Linux helper for DaVinci Resolve projects that contain AAC audio.

It watches the Resolve MediaPool, converts AAC audio to Resolve-friendly PCM,
and replaces the imported clip automatically. Video streams are copied, not
re-encoded. Original files stay untouched.

## Requirements

- DaVinci Resolve on Linux
- Python 3
- `ffmpeg` and `ffprobe`
- Resolve scripting enabled

Enable scripting in Resolve:

```text
Preferences -> System -> General -> External scripting
```

## Install

Download the latest release archive:

```bash
curl -L https://github.com/RayDurlok/DaVinci-Resolve-AAC-Scripts-for-Linux/releases/latest/download/resolve-aac-tools-linux.tar.gz -o resolve-aac-tools-linux.tar.gz
tar xzf resolve-aac-tools-linux.tar.gz
cd resolve-aac-tools
./install_user_tools.sh
```

Or clone the repository and run:

```bash
./install_user_tools.sh
```

This installs command wrappers and Resolve menu scripts for the current user.

## Start Resolve With AAC Watcher

Use this as the main workflow:

```bash
resolve-with-aac-mediapool-watch
```

Then drag media into Resolve as usual. AAC media is converted to MOV/PCM and the
MediaPool item is replaced automatically.

When started in an existing project, the watcher also scans already imported
online MediaPool clips. Offline media is skipped.

To keep generated files in a cache folder instead of beside the source media:

```bash
RESOLVE_AAC_CACHE_DIR="$HOME/.cache/resolve-aac-remux" resolve-with-aac-mediapool-watch
```

## Other Commands

Start or stop only the MediaPool watcher:

```bash
resolve-aac-mediapool-watch
resolve-aac-mediapool-watch-stop
```

Fix timeline clips:

```bash
resolve-aac-current-clip
resolve-aac-timeline-watch
resolve-aac-timeline-watch-stop
```

Batch convert files or folders:

```bash
./resolve_aac_import.py --overwrite /path/to/media-or-folder
```

## Output

Default output:

```text
<source-folder>/aac_remux/
```

Cached output:

```text
$RESOLVE_AAC_CACHE_DIR/
```

## Experimental FFmpeg Patch

Some Resolve Linux builds ship FFmpeg with AAC disabled. This repo includes an
unsupported patch path that builds AAC-enabled FFmpeg libraries and installs
them into `/opt/resolve/libs` with a backup:

```bash
./build_resolve_ffmpeg_aac.sh
./install_resolve_ffmpeg_aac.sh
```

Restore the latest backup:

```bash
./restore_resolve_ffmpeg_backup.sh
```

## License

GPLv3.
