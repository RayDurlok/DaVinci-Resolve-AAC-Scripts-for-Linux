#!/usr/bin/env python3
"""Remux every AAC clip in the current project's media pool now (one pass).

The on-demand opposite of resolve_aac_restore.py: convert any AAC media in the
media pool to PCM and repoint the clips, in a single pass. The MediaPool watcher
does this continuously for new imports; this catches media that is already there.

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

    from types import SimpleNamespace

    from resolve_aac_config import load_config
    from resolve_aac_mediapool_watch import new_scan_state, scan_once

    cfg = load_config()
    cache_dir = Path(cfg["cache_dir"]).expanduser() if cfg.get("use_cache") else None
    args = SimpleNamespace(
        output_dir=None,
        cache_dir=cache_dir,
        overwrite=False,
        quiet=False,
        retry=False,
    )
    state = new_scan_state()
    changed = scan_once(args, state)
    return f"Remuxed {changed} AAC clip(s) in the media pool."


if __name__ == "__main__":
    try:
        result = run()
        _log("remux_all OK: " + result)
        print(result)
        raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        tb = traceback.format_exc()
        _log("remux_all CRASHED:\n" + tb)
        print("Remux failed (see " + str(_LOG) + "):\n" + tb)
        raise SystemExit(1)
