#!/usr/bin/env python3
"""Restore original source files for the currently open DaVinci Resolve project.

Undoes the AAC remux: every MediaPool clip that was repointed to a generated
remux is put back to its original file (the remux never touched the original).
Uses the map written at remux time (~/.config/resolve-aac-tools/remux_map.json).

Runs both standalone (the tray action) and inside Resolve (Workspace > Scripts).
Any failure is logged to /tmp/DaVinciResolveToolkit-menu.log for diagnostics.
"""

import sys
import traceback
from pathlib import Path

_LOG = Path("/tmp/DaVinciResolveToolkit-menu.log")


def _log(text):
    try:
        with _LOG.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except Exception:
        pass


def run():
    # Resolve runs menu scripts without setting __file__, but it does put the
    # (resolved) script folder on sys.path, so sibling imports still work.
    try:
        script_dir = Path(__file__).resolve().parent
    except NameError:
        script_dir = Path.cwd()
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    import subprocess
    import time

    from resolve_aac_import import get_resolve
    from resolve_aac_timeline import (
        iter_media_pool_items,
        load_remux_map,
        media_pool_item_path,
    )

    # Stop the watcher first, or it immediately re-remuxes what we restore.
    stop_file = Path("/tmp/resolve_aac_mediapool_watch.stop")
    try:
        stop_file.write_text("stop\n")
    except OSError:
        pass
    try:
        subprocess.run(["pkill", "-f", "resolve_aac_mediapool_watch.py"], check=False)
    except Exception:
        pass
    time.sleep(1)

    resolve = get_resolve()
    if resolve is None:
        raise RuntimeError("Could not connect to DaVinci Resolve.")
    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject() if project_manager else None
    if project is None:
        raise RuntimeError("No project is open in DaVinci Resolve.")

    media_pool = project.GetMediaPool()
    remux_map = load_remux_map()

    restored = 0
    missing = 0
    failed = 0
    for item in iter_media_pool_items(media_pool.GetRootFolder()):
        raw_path = media_pool_item_path(item)
        if not raw_path:
            continue
        key = str(Path(raw_path).expanduser().resolve())
        original = remux_map.get(key) or remux_map.get(raw_path)
        if not original:
            continue
        if not Path(original).exists():
            missing += 1
            continue
        replacer = getattr(item, "ReplaceClipPreserveSubClip", None) or item.ReplaceClip
        if replacer(str(original)):
            restored += 1
        else:
            failed += 1

    message = f"Restored {restored} clip(s) to their original source. MediaPool watcher stopped."
    if missing:
        message += f" ({missing} original file(s) missing.)"
    if failed:
        message += f" ({failed} could not be replaced.)"
    return message


if __name__ == "__main__":
    try:
        result = run()
        _log("restore OK: " + result)
        print(result)
        raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        tb = traceback.format_exc()
        _log("restore CRASHED:\n" + tb)
        print("Restore failed (see " + str(_LOG) + "):\n" + tb)
        raise SystemExit(1)
