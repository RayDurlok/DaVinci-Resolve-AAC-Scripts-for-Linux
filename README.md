# DaVinci Resolve AAC Tools for Linux

Install guide video:
https://youtu.be/cBxr6CLhnVI

Inspired by: https://github.com/jchai01/davinci-resolve-aac-workaround-macro

A small Linux tray app for DaVinci Resolve projects that contain AAC audio.

It watches Resolve, converts AAC audio to Resolve-friendly PCM, and replaces
imported clips automatically. Video streams are copied, not re-encoded. Original
files stay untouched.

For AAC **exports**:

- **Resolve 21:** enable the tray toggle `Remux all exports in webfriendly AAC`.
- **Resolve 20:** install the optional Toxblh AAC export plugin
  (https://github.com/Toxblh/davinci-linux-aac-codec) with one click in the tray.
  This plugin does **not** work on Resolve 21.

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

The installed `resolve-aac-tray` command starts the tray in the background and
returns your terminal immediately. Its startup log is written to
`/tmp/resolve_aac_tray.log`.

Then work in Resolve as usual.

Tray basics:

- Left-click the tray icon to start Resolve with AAC watching.
- Right-click the tray icon to change settings.
- Enable `Watch manual Resolve starts` to start the watcher when Resolve is opened normally.
- Fresh installs leave `Start tray at login` off. Enable it only if you want the tray icon available after login.
- For AAC exports on **Resolve 21**: enable `Remux all exports in webfriendly AAC` (off by default). It watches your render outputs and converts FLAC, PCM, and broken AAC audio to browser-friendly AAC-LC in place, with a desktop notification when done.
- On **Resolve 20** only: `AAC export plugin: Install` adds AAC as a native export option (Toxblh plugin). It does not work on Resolve 21.
- Use `Resolve font fix: Install` once if Resolve/Fusion does not see user-installed fonts.
- Click either optional install entry again after it shows `Installed` to uninstall it.

The tray can store generated MOV/PCM files either in a cache folder or beside the
source media in `<source-folder>/aac_remux/`. Fresh installs use source folders
by default. If you enable `Use cache folder`, the default cache path is
`~/.cache/resolve-aac-remux`.

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

To uninstall the user tools from a release folder or source checkout:

```bash
./uninstall_user_tools.sh
```

The uninstaller removes the commands, desktop files, Resolve menu scripts,
autostart entry, config, and optional font-fix desktop override. It keeps cached
remux files in `~/.cache/resolve-aac-remux` unless you pass `--remove-cache`.

PySide6 is required — the tray is how these tools are meant to be used:

```bash
resolve-aac-tray
resolve-aac-start
```

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

The optional AAC export plugin (Toxblh's `davinci-linux-aac-codec`) is separate
from the watcher and **only works on DaVinci Resolve 20**. It installs once into
Resolve's `IOPlugins` folder; restart Resolve after installing. On Resolve 21 it
no longer works (Resolve crashes on export) — use the `Remux all exports in
webfriendly AAC` toggle instead.

The export remux watcher is a separate tray toggle for AAC exports, off by
default. When enabled, it detects Resolve's render outputs, waits until Resolve
finishes writing, and rewrites the audio stream as browser-friendly AAC-LC while
copying the video stream. It converts FLAC, PCM, and broken/incomplete AAC and
leaves healthy AAC untouched; an audio-only PCM render (PCM with no video, e.g. a
WAV master) is left as PCM. It only converts files rendered while it runs and
never touches your source clips or the PCM cache. It replaces the exported file
in place — no watch folder, sidecar, or backup file.

The optional Resolve font fix is also a one-time install, not a background
watcher. It installs a local Resolve launcher wrapper and desktop override so
Resolve starts with additional Fusion font paths such as `/usr/local/share/fonts`,
`~/.local/share/fonts`, and `~/.fonts`. Restart Resolve after applying or
uninstalling it.

The optional native file dialogs toggle (`Native file dialogs`) is off by default.
When enabled it installs a Qt `platformthemes` plugin (detected on your system,
distro-agnostic) so Resolve routes its standard file dialogs — Export Still,
Import, Export Project — through the desktop's native portal/KDE dialog after a
restart. It also replaces Resolve's non-native Deliver `File Destination` browser
with a native "Save as" dialog: the watcher detects that window, closes it (by
sending it `WM_DELETE_WINDOW` directly so it works regardless of focus), opens
the native picker, and writes the chosen folder and name into the render
`Location` / `Custom Name` through the scripting API. That intercept runs only
while the MediaPool watcher runs. The `Set render location...` action opens the
same picker on demand. Turning the toggle off removes the plugin again (restart
Resolve to revert). Requires `python3-gobject` (gi) and `kdialog`, which the
installer adds; the focus-independent close uses `python3-xlib` when present and
otherwise falls back to sending Escape via ydotool.

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
resolve-aac-export-watch
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

Run the export remux watcher directly:

```bash
resolve-aac-export-watch --detect-resolve-outputs --replace --no-backup
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

## Repository Layout

```text
scripts/                  User-facing Resolve AAC tools
qt-plugins/               Native-dialog Qt platformtheme plugin (generated by the toggle)
test-media/               Small AAC test files
```

## License

GPLv3.
