# DaVinci Resolve AAC Tools for Linux

Inspired by: https://github.com/jchai01/davinci-resolve-aac-workaround-macro

A small set of Linux helpers for DaVinci Resolve projects that contain AAC audio.

The main tool watches the Resolve MediaPool, converts AAC audio to
Resolve-friendly PCM, and replaces imported clips automatically. Optional
timeline and batch-conversion tools are included as fallbacks. Video streams are
copied, not re-encoded. Original files stay untouched.

## Requirements

- DaVinci Resolve on Linux
- Python 3
- `ffmpeg` and `ffprobe`
- Resolve scripting enabled
- Optional tray app: PySide6

Tested on Fedora with DaVinci Resolve Studio.

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
./scripts/install_user_tools.sh
```

This installs all included tools for the current user: command wrappers, Resolve
menu scripts, the recommended MediaPool watcher, and the optional timeline
fallback tools. The installer checks for `python3`, `ffmpeg`, and `ffprobe` and
can prompt to install missing dependencies on common Linux distributions. It
also checks PySide6 and can offer to install it for the optional tray app.

PySide6 is only required for:

```bash
resolve-aac-tray
resolve-aac-start
```

The MediaPool watcher, menu scripts, and command-line tools work without it.

For an unattended install:

```bash
./install_user_tools.sh --yes
```

To skip dependency checks:

```bash
./install_user_tools.sh --no-deps
```

Installed commands:

```bash
resolve-aac-import
resolve-aac-watch
resolve-with-aac-mediapool-watch
resolve-aac-mediapool-watch
resolve-aac-mediapool-watch-stop
resolve-aac-current-clip
resolve-aac-timeline-watch
resolve-aac-timeline-watch-stop
resolve-aac-tray
resolve-aac-start
```

The same tools are also available in Resolve:

```text
Workspace -> Scripts -> Edit -> Resolve AAC Tools
```

## Start Resolve With AAC Watcher

This is the recommended workflow:

```bash
resolve-aac-start
```

This opens the tray app and starts Resolve with the MediaPool watcher. Then drag
media into Resolve as usual. AAC media is converted to MOV/PCM and the MediaPool
item is replaced automatically.

For best results, import clips into the MediaPool first and then edit them into
the timeline.

When started in an existing project, the watcher also scans already imported
online MediaPool clips. This also works for projects that already have edited
clips in the timeline, as long as those timeline clips still reference the
MediaPool items. Offline media is skipped.

Dragging AAC media directly into the timeline can work, but Resolve may keep an
old waveform cache. In that case audio can play while the waveform is missing.
Restarting Resolve usually rebuilds the waveform. You can also use
`resolve-aac-current-clip` or `resolve-aac-timeline-watch` as a fallback.

To keep generated files in a cache folder instead of beside the source media:

```bash
RESOLVE_AAC_CACHE_DIR="$HOME/.cache/resolve-aac-remux" resolve-with-aac-mediapool-watch
```

## Tray App

The optional tray app can start Resolve with the MediaPool watcher and choose
where generated MOV/PCM files are stored:

```bash
resolve-aac-tray
```

Left-click the tray icon to start Resolve with the MediaPool watcher. Right-click
it to open settings and actions.

To open the tray and start Resolve immediately:

```bash
resolve-aac-start
```

It can switch between:

- cache folder output, for example `~/.cache/resolve-aac-remux`
- source-folder output, using `<source-folder>/aac_remux/`
- tray autostart at login

The tray app requires PySide6. If PySide6 is missing, the CLI tools and Resolve
menu scripts still work.

Tray autostart only opens the tray icon. Resolve starts when you left-click the
tray icon or run `resolve-aac-start`.

When Resolve is started through the tray or `resolve-aac-start`, closing Resolve
also stops the MediaPool watcher. The tray icon stays available.

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

From a source checkout:

```bash
./experiments/ffmpeg-patch/build_resolve_ffmpeg_aac.sh
./experiments/ffmpeg-patch/install_resolve_ffmpeg_aac.sh
```

This did not solve AAC playback reliably in testing. The replacement libraries
could decode AAC outside Resolve, but Resolve still failed to play AAC audio
correctly.

Restore the latest backup:

```bash
./experiments/ffmpeg-patch/restore_resolve_ffmpeg_backup.sh
```

This path is unsupported and not recommended for normal use. The code is kept in
the repository for anyone who wants to continue experimenting.

## Repository Layout

```text
scripts/                  User-facing Resolve AAC tools
experiments/ffmpeg-patch/ Failed FFmpeg library replacement experiment
experiments/io-plugin/    DaVinci Resolve IOPlugin probe experiment
test-media/               Small AAC test files
```

## License

GPLv3.
