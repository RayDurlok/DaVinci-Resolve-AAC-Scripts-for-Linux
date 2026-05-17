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

Installed commands:

```bash
resolve-with-aac-mediapool-watch
resolve-aac-mediapool-watch
resolve-aac-mediapool-watch-stop
resolve-aac-current-clip
resolve-aac-timeline-watch
resolve-aac-timeline-watch-stop
```

The same tools are also available in Resolve:

```text
Workspace -> Scripts -> Edit
```

## Start Resolve With AAC Watcher

This is the recommended workflow:

```bash
resolve-with-aac-mediapool-watch
```

Then drag media into Resolve as usual. AAC media is converted to MOV/PCM and the
MediaPool item is replaced automatically.

When started in an existing project, the watcher also scans already imported
online MediaPool clips. This also works for projects that already have edited
clips in the timeline, as long as those timeline clips still reference the
MediaPool items. Offline media is skipped.

To keep generated files in a cache folder instead of beside the source media:

```bash
RESOLVE_AAC_CACHE_DIR="$HOME/.cache/resolve-aac-remux" resolve-with-aac-mediapool-watch
```

## Other Commands

### MediaPool Tools

Use these for already imported media and new imports. This is the recommended
option for edited projects because it replaces MediaPool items instead of
directly editing the timeline.

Start or stop only the MediaPool watcher:

```bash
resolve-aac-mediapool-watch
resolve-aac-mediapool-watch-stop
```

### Timeline Tools

Use these as a fallback when timeline clips do not update from the MediaPool
replacement.

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

## Failed Experiment: FFmpeg Patch

Some Resolve Linux builds ship FFmpeg libraries with AAC disabled. This repo
includes experimental scripts that build AAC-enabled FFmpeg libraries and install
them into `/opt/resolve/libs` with a backup:

```bash
./build_resolve_ffmpeg_aac.sh
./install_resolve_ffmpeg_aac.sh
```

This did not solve AAC playback reliably in testing. The replacement libraries
could decode AAC outside Resolve, but Resolve still failed to play AAC audio
correctly.

Restore the latest backup:

```bash
./restore_resolve_ffmpeg_backup.sh
```

This path is unsupported and not recommended for normal use. The code is kept in
the repository for anyone who wants to continue experimenting.

## License

GPLv3.
