# DaVinci Resolve AAC Tools for Linux

Inspired by: https://github.com/jchai01/davinci-resolve-aac-workaround-macro

Optional AAC export plugin by Toxblh:
https://github.com/Toxblh/davinci-linux-aac-codec

A small Linux tray app for DaVinci Resolve projects that contain AAC audio.

It watches Resolve, converts AAC audio to Resolve-friendly PCM, and replaces
imported clips automatically. Video streams are copied, not re-encoded. Original
files stay untouched.

## Requirements

- DaVinci Resolve on Linux
- Python 3
- `ffmpeg` and `ffprobe`
- PySide6
- Resolve scripting enabled

Tested on Fedora with DaVinci Resolve Studio.

Enable scripting in Resolve:

```text
Preferences -> System -> General -> External scripting using: Local
```

## Quick Start

Install the latest release:

```bash
curl -L https://github.com/RayDurlok/DaVinci-Resolve-AAC-Scripts-for-Linux/releases/latest/download/resolve-aac-tools-linux.tar.gz -o resolve-aac-tools-linux.tar.gz
tar xzf resolve-aac-tools-linux.tar.gz
cd resolve-aac-tools
./install_user_tools.sh
```

Start the tray app:

```bash
resolve-aac-tray
```

Then work in Resolve as usual.

Tray basics:

- Left-click the tray icon to start Resolve with AAC watching.
- Right-click the tray icon to change settings.
- Enable `Watch manual Resolve starts` to start the watcher when Resolve is opened normally.
- Enable `Start tray at login` if you want the tray icon available after login.
- Use `AAC export plugin: Install` once if you also want AAC as an export option.
- Use `Resolve font fix: Apply` once if Resolve/Fusion does not see user-installed fonts.
- Use the matching `Uninstall` actions if you want to remove either optional install.

The tray can store generated MOV/PCM files either in a cache folder or beside the
source media in `<source-folder>/aac_remux/`.

## Install Notes

The installer adds the tray app, command wrappers, Resolve menu scripts, and
fallback tools for the current user. It checks for `python3`, `ffmpeg`,
`ffprobe`, and PySide6, and can offer to install missing dependencies on common
Linux distributions. PySide6 is checked on every distro; package names can vary.

For a source checkout:

```bash
./scripts/install_user_tools.sh
```

For an unattended install from the release folder or source checkout:

```bash
./install_user_tools.sh --yes
```

To skip dependency checks:

```bash
./install_user_tools.sh --no-deps
```

PySide6 is required for the tray app:

```bash
resolve-aac-tray
resolve-aac-start
```

The MediaPool watcher, Resolve menu scripts, and command-line tools can still
work without PySide6, but they are fallback tools. The intended app experience is
the tray.

## How It Works

When Resolve imports AAC media, the watcher creates a Resolve-friendly MOV/PCM
copy and replaces the MediaPool item. This also works for projects that already
have edited clips in the timeline, as long as those timeline clips still
reference the MediaPool items. Offline media is skipped.

For best results, import clips into the MediaPool first and then edit them into
the timeline.

Dragging AAC media directly into the timeline can work, but Resolve may keep an
old waveform cache. In that case audio can play while the waveform is missing.
Restarting Resolve usually rebuilds the waveform. You can also use
`resolve-aac-current-clip` or `resolve-aac-timeline-watch` as a fallback.

To open the tray and start Resolve immediately from a terminal:

```bash
resolve-aac-start
```

When Resolve is started through the tray or `resolve-aac-start`, closing Resolve
also stops the MediaPool watcher. The tray icon stays available.

The optional AAC export plugin is separate from the watcher. It comes from
Toxblh's `davinci-linux-aac-codec` project and is installed once into Resolve's
`IOPlugins` folder. Resolve loads it on startup, so restart Resolve after
installing it.

The optional Resolve font fix is also a one-time install, not a background
watcher. It installs a local Resolve launcher wrapper and desktop override so
Resolve starts with additional Fusion font paths such as `/usr/local/share/fonts`,
`~/.local/share/fonts`, and `~/.fonts`. Restart Resolve after applying or
uninstalling it.

## Optional Tools

These are installed too, but most users only need the tray app.

Resolve menu scripts:

```text
Workspace -> Scripts -> Edit -> Resolve AAC Tools
```

Installed commands:

```bash
resolve-aac-tray
resolve-aac-start
resolve-aac-mediapool-watch
resolve-aac-mediapool-watch-stop
resolve-aac-current-clip
resolve-aac-timeline-watch
resolve-aac-timeline-watch-stop
resolve-aac-import
resolve-aac-watch
resolve-with-fonts
```

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
resolve-aac-import /path/to/media-or-folder
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
