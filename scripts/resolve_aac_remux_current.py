#!/usr/bin/env python3
"""Remux the current timeline clip's AAC source to PCM (single clip, revertible).

Single-clip version of resolve_aac_remux_all.py: take the clip under the
playhead, replace its Media Pool source with a PCM remux and record the mapping
so "Restore Original Sources" can undo it. The output location follows the
settings (external cache when caching is enabled, else next to the source),
exactly like the MediaPool watcher and "Remux All".

Runs standalone (a tray action) and inside Resolve (Workspace > Scripts).
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

    from resolve_aac_config import load_config
    from resolve_aac_import import get_resolve
    from resolve_aac_mediapool_watch import replace_media_pool_item
    from resolve_aac_timeline import current_timeline_item

    cfg = load_config()
    cache_dir = Path(cfg["cache_dir"]).expanduser() if cfg.get("use_cache") else None

    resolve = get_resolve()
    if resolve is None:
        raise RuntimeError("Could not connect to DaVinci Resolve.")
    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject() if project_manager else None
    if project is None:
        raise RuntimeError("No project is open in DaVinci Resolve.")
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        raise RuntimeError("No timeline is open. Put the playhead over the clip to remux.")

    item = current_timeline_item(project, timeline)
    media_pool_item = item.GetMediaPoolItem()
    if media_pool_item is None:
        raise RuntimeError("Current timeline clip has no Media Pool item.")

    output_path = replace_media_pool_item(media_pool_item, cache_dir=cache_dir)
    if output_path:
        return f"Remuxed current clip -> {Path(output_path).name}"
    return "Current clip needs no remux (not AAC, offline, or already remuxed)."


if __name__ == "__main__":
    try:
        result = run()
        _log("remux_current OK: " + result)
        print(result)
        raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        tb = traceback.format_exc()
        _log("remux_current CRASHED:\n" + tb)
        print("Remux failed (see " + str(_LOG) + "):\n" + tb)
        raise SystemExit(1)
