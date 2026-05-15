#!/usr/bin/env python3

import argparse
import sys
import time
import traceback
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from resolve_aac_import import get_resolve
from resolve_aac_timeline import (
    LOG_PATH,
    is_generated_remux_path,
    log,
    replace_audio_item,
    timeline_item_frame,
    timeline_item_path,
    timeline_items,
)


STOP_PATH = Path("/tmp/resolve_aac_timeline_watch.stop")


def item_key(item):
    try:
        unique_id = item.GetUniqueId()
    except Exception:
        unique_id = ""

    try:
        path = timeline_item_path(item)
        track = item.GetTrackTypeAndIndex()
        return "%s:%s:%s:%s:%s" % (
            unique_id,
            path,
            track[1] if track and len(track) > 1 else "",
            timeline_item_frame(item.GetStart(False)),
            timeline_item_frame(item.GetEnd(False)),
        )
    except Exception:
        try:
            return unique_id or str(id(item))
        except Exception:
            return str(id(item))


def timeline_signature(audio_items):
    return tuple(sorted(item_key(item) for item in audio_items))


def get_context():
    resolve = get_resolve()
    if not resolve:
        raise RuntimeError("Could not connect to Resolve")

    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject() if project_manager else None
    if not project:
        raise RuntimeError("Resolve has no current project")

    timeline = project.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError("Resolve has no current timeline")

    return project, timeline, project.GetMediaPool()


def scan_once(args, state):
    project, timeline, media_pool = get_context()
    changed = 0
    audio_items = list(timeline_items(timeline, "audio"))
    signature = timeline_signature(audio_items)

    if signature == state["signature"] and not args.retry:
        return 0
    state["signature"] = signature

    for audio_item in audio_items:
        key = item_key(audio_item)
        if key in state["processed"] and not args.retry:
            continue

        try:
            input_path = timeline_item_path(audio_item)
            if is_generated_remux_path(input_path):
                state["processed"].add(key)
                continue

            path_key = str(input_path)
            cached = state["source_cache"].get(path_key)
            if cached == "non-aac":
                state["processed"].add(key)
                continue

            output_path = replace_audio_item(
                timeline=timeline,
                media_pool=media_pool,
                audio_item=audio_item,
                overwrite=args.overwrite,
                output_dir_override=args.output_dir,
                cache_dir=args.cache_dir,
                keep_original=args.keep_original,
                quiet=args.quiet,
            )
            state["processed"].add(key)
            if output_path:
                state["source_cache"][path_key] = "converted"
                changed += 1
            else:
                state["source_cache"][path_key] = "non-aac"
        except Exception as exc:
            state["processed"].add(key)
            log("Watcher item failed: " + str(exc))
            log(traceback.format_exc())

    return changed


def main():
    parser = argparse.ArgumentParser(
        description="Watch the current Resolve timeline and replace dropped AAC audio with PCM remuxes."
    )
    parser.add_argument("--interval", type=float, default=3.0, help="Polling interval in seconds")
    parser.add_argument("--once", action="store_true", help="Scan once and exit")
    parser.add_argument("--retry", action="store_true", help="Retry items already seen by this watcher process")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite converted media")
    parser.add_argument("-o", "--output-dir", type=Path, help="Override output directory")
    parser.add_argument("--cache-dir", type=Path, help="Store remuxes in an external cache instead of next to source media")
    parser.add_argument("--keep-original", action="store_true", help="Keep original AAC timeline audio clips")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if STOP_PATH.exists():
        STOP_PATH.unlink()

    log("=== Resolve AAC Timeline Watch started ===")
    log(f"Log: {LOG_PATH}")
    log(f"Stop file: {STOP_PATH}")

    state = {
        "processed": set(),
        "source_cache": {},
        "signature": None,
    }
    while True:
        try:
            changed = scan_once(args, state)
            if changed:
                log(f"Watcher replaced {changed} AAC clip(s)")
        except Exception as exc:
            log("Watcher scan failed: " + str(exc))
            log(traceback.format_exc())

        if args.once or STOP_PATH.exists():
            break
        time.sleep(args.interval)

    log("=== Resolve AAC Timeline Watch stopped ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
