# Changelog

All notable changes to this project are documented here. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/). Releases before this
file are tracked through git tags and GitHub releases (latest: `v0.1.8`).

## [Unreleased]

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

### Changed
- Installer now also installs `python3-gobject` (gi) and `kdialog`, used by the
  native "Save as" picker.
- `resolve-with-fonts.sh` and `resolve-with-aac-mediapool-watch.sh` export the
  xdg-desktop-portal Qt platform theme when the plugin is present.
