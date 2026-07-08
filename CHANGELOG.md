# Changelog

All notable changes to this project are documented here. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/). Releases before this
file are tracked through git tags and GitHub releases (latest: `v0.1.11`).

## [Unreleased]

## [0.2.1] - 2026-07-09

### Changed
- Renamed the RPM package to `davinci-resolve-toolkit` so `dnf install` matches
  the app name and Copr project. The `resolve-aac-*` commands and user config are
  unchanged.

## [0.2.0] - 2026-07-09

### Added
- Available from Fedora Copr (`dnf copr enable raydurlok/davinci-resolve-toolkit`)
  and as a Discover / GNOME Software tile.

### Changed
- Added a trademark notice (not affiliated with or endorsed by Blackmagic Design)
  to the README and AppStream metadata.

## [0.1.18] - 2026-07-09

### Added
- "Restore Original Sources": undo AAC remuxing for the currently open project,
  from the tray or from Resolve's Scripts menu. It stops the MediaPool watcher
  first so the restored clips are not immediately remuxed again.
- "Remux All AAC Media" and a reworked single-clip "Current Clip" (also the
  `resolve-aac-current-clip` command), both as revertible Media Pool
  replacements that follow the cache setting and record every remux so
  "Restore Original Sources" can undo them.
- Store screenshots and a documented "Undo and on-demand remux" section in the
  README; the settings "menu scripts" section now mentions restore/remux.

### Changed
- Rebranded to "DaVinci Resolve Toolkit" (app name, settings window, desktop
  entry, and AppStream/Discover metadata).
- The MediaPool watcher now exits when Resolve closes and when the tray quits,
  instead of lingering as an orphan.

### Fixed
- Resolve menu scripts no longer crash when Resolve runs them without `__file__`.

### Removed
- Two stray desktop files that hardcoded a personal home path.

## [0.1.17] - 2026-07-08

### Fixed
- Native file dialogs (Export Still/Import) now also work when Resolve is
  started from the application menu: the portal environment is set in the
  font-fix launch wrapper too, not only in the tray launch actions.

## [0.1.16] - 2026-07-08

### Added
- The welcome page shows the app version.

### Fixed
- Native file dialogs from an RPM install: the portal plugin symlink is created
  in a user-writable directory instead of read-only `/usr`.

## [0.1.15] - 2026-07-08

### Changed
- Resolve version detection is cached against the Resolve binary's mtime and
  only re-scans when Resolve actually changes, so manual updates are picked up
  and window focus stays cheap.

## [0.1.14] - 2026-07-08

### Changed
- Re-detect the Resolve version after running the updater (on window focus).

## [0.1.13] - 2026-07-08

### Changed
- Show only the main "DaVinci Resolve Toolkit" entry in the application menu;
  the secondary launchers are hidden (`NoDisplay`).

## [0.1.12] - 2026-07-08

### Added
- Modern first-run setup / settings window (PySide6) with welcome, preferences,
  paths, export, and extras pages and automatic dark/light theming, backed by a
  shared config module and reused by the tray.
- RPM packaging: system-wide install, CLI wrappers, AppStream metadata and a
  Discover tile, desktop entries, and a local `build-rpm.sh`.
- App icon shipped for the Discover tile, application menu, and tray.

### Fixed
- Export remux for ProRes/`.mov` renders (the temporary container is derived
  from the source extension) and honor the logging toggle.

## [0.1.11] - 2026-07-07

### Changed
- Tray: reorganized the menu into clearer groups for launch actions, toggles,
  cache settings, tools, logs, and quit.
- Tray: the AAC export plugin entry is now labelled "(Resolve 20 only)".
- Tray: renamed the `Native file dialogs` toggle to `Native KDE file dialogs`.
- Tray: renamed `Use cache folder` to `Use single cache folder`.
- Resolve launch wrappers now preload the system GLib stack when Resolve's
  bundled GLib is missing `g_once_init_leave_pointer` on Fedora-like systems.
- Installer now starts the tray at the end of a fresh install, and restarts a
  running tray (and its watchers) when re-run, so updates take effect without a
  manual restart.

### Added
- Tray toggle `Mute notifications`.
- Tray action `Install Resolve ZIP from Downloads` plus the
  `resolve-update-from-downloads` command and desktop entry.
- Tray startup now sets Resolve's `Show Stacked Timelines` user preference on
  when the preference file is available.
- `Native KDE file dialogs` now also replaces Resolve's MediaPool relink
  `Select Source Folder` browser with the native KDE folder picker for a single
  clip or the current bin (relink via the scripting API). Multiple selected bins,
  which the scripting API cannot enumerate, keep Resolve's own dialog — the
  watcher checks the API before closing Resolve's dialog and leaves it open when
  it cannot enumerate clips.

### Fixed
- Export remux verification accepts valid AAC-LC files when `ffprobe` omits the
  human-readable `profile=LC` field but reports `mp4a.40.2` and AAC extradata.
- Export remux detection now ignores read-only Resolve file handles, so imported
  source clips are not mistaken for render outputs.
- Export remux watcher marks failed detected outputs as seen to avoid retry loops
  until the file changes again.

### Removed
- Tray menu entry `Set render location...`. The native render-location picker is
  still used automatically by the `Native KDE file dialogs` intercept; only the
  redundant on-demand menu action was dropped (`set_render_location.py` stays).

## [0.1.10] - 2026-06-18

### Fixed
- Tray no longer starts the MediaPool watcher from loose process-name matches
  when `Watch manual Resolve starts` is enabled. Resolve detection now checks
  real `/proc` process information and only starts the watcher on an actual
  Resolve process transition.
- Timeline watcher logging now handles non-ASCII file names safely.

## [0.1.9] - 2026-06-10

### Added
- Native file dialogs for Resolve, behind a tray toggle `Native file dialogs`
  (off by default):
  - Installs/removes a Qt `platformthemes` plugin via a symlink to the system
    plugin (generic, distro-agnostic detection) so Resolve's standard file
    dialogs — Export Still, Import, Export Project — use the desktop's native
    portal/KDE dialog after a restart.
  - Replaces Resolve's non-native Deliver `File Destination` browser with a
    native portal "Save as" dialog and writes the chosen folder/name into the
    render `Location` / `Custom Name` via the scripting API. The intercept is
    lifecycle-coupled to the MediaPool watcher.
  - `Set render location...` tray action opens the same native picker on demand.
- `set_render_location.py` and `resolve_render_location_watch.py`, shipped in the
  release archive.
- Export remux watcher can send a desktop notification (`notify-send`) when a
  remux finishes (and if one fails), behind a new `--notify` flag. The tray passes
  it, so you get a popup when an export has been converted to AAC.

### Changed
- Export remux watcher now converts FLAC, PCM, and broken/incomplete AAC audio to
  browser-friendly AAC-LC (previously it only repaired broken AAC metadata).
  Healthy AAC is left untouched, and audio-only PCM renders (PCM with no video,
  e.g. WAV masters) are kept as PCM.
- Deliver "File Destination" intercept now closes Resolve's dialog by sending it
  `WM_DELETE_WINDOW` directly (via Xlib), instead of blasting Escape at whatever
  window happens to be focused. This is focus-independent and fixes having to
  click Export twice (first click previously left both Resolve's dialog and the
  native picker open). Escape via ydotool remains a fallback.
- Export remux watcher in `--detect-resolve-outputs` mode skips the MediaPool
  watcher's PCM intermediates (the `resolve-aac-remux` cache and `aac_remux/`
  folders) and only converts files created during the current watch session, so
  it never touches input or source clips. It polls fast (0.2s, set by the tray,
  with a cached Resolve-PID lookup) because Resolve holds a fast render's output
  open for writing only briefly (sub-second); the previous 1–3s polling missed
  those. (An earlier attempt that only looked at write-opened handles also missed
  real renders and was reverted.)
- Renamed the tray toggle `Remux exports to webfriendly AAC` to
  `Remux all exports in webfriendly AAC`.
- Installer now also installs `python3-gobject` (gi) and `kdialog`, used by the
  native "Save as" picker.
- `resolve-with-fonts.sh` and `resolve-with-aac-mediapool-watch.sh` export the
  xdg-desktop-portal Qt platform theme when the plugin is present.

### Docs
- Clarified that the Toxblh AAC export plugin works only on DaVinci Resolve 20;
  on Resolve 21 use the `Remux all exports in webfriendly AAC` toggle. Trimmed the
  README (removed the failed FFmpeg-patch section).
