# Changelog

All notable changes to this project are documented here. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/). Releases before this
file are tracked through git tags and GitHub releases (latest: `v0.1.10`).

## [Unreleased]

### Changed
- Tray: reorganized the menu into clearer groups for launch actions, toggles,
  cache settings, tools, logs, and quit.
- Tray: the AAC export plugin entry is now labelled "(Resolve 20 only)".
- Tray: renamed the `Native file dialogs` toggle to `Native KDE file dialogs`.
- Tray: renamed `Use cache folder` to `Use single cache folder`.
- Resolve launch wrappers now preload the system GLib stack when Resolve's
  bundled GLib is missing `g_once_init_leave_pointer` on Fedora-like systems.

### Added
- Tray toggle `Mute notifications`.
- Tray action `Install Resolve ZIP from Downloads` plus the
  `resolve-update-from-downloads` command and desktop entry.
- Tray startup now sets Resolve's `Show Stacked Timelines` user preference on
  when the preference file is available.

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
