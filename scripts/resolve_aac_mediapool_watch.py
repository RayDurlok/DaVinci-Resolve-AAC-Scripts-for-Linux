#!/usr/bin/env python3

import argparse
import subprocess
import sys
import time
import traceback
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from resolve_aac_import import convert, get_resolve
from resolve_aac_timeline import (
    DEFAULT_OUTPUT_SUBDIR,
    LOG_PATH,
    clip_property,
    is_generated_remux_path,
    iter_media_pool_items,
    cache_output_dir_for_input,
    log,
    media_pool_item_path,
    output_dir_for_input,
    record_remux,
)


STOP_PATH = Path("/tmp/resolve_aac_mediapool_watch.stop")
RETRY_BASE_SECONDS = 5.0
RETRY_MAX_SECONDS = 60.0


def resolve_is_running():
    try:
        return subprocess.run(
            ["pgrep", "-f", "/opt/resolve/bin/resolve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
    except Exception:
        return True  # can't tell -> don't exit prematurely


def get_context():
    resolve = get_resolve()
    if not resolve:
        raise RuntimeError("Could not connect to Resolve")

    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject() if project_manager else None
    if not project:
        raise RuntimeError("Resolve has no current project")

    media_pool = project.GetMediaPool()
    if not media_pool:
        raise RuntimeError("Resolve has no media pool")

    return media_pool


def item_key(item):
    try:
        media_id = item.GetMediaId()
    except Exception:
        media_id = ""

    try:
        return "%s:%s" % (media_id, media_pool_item_path(item))
    except Exception:
        return media_id or str(id(item))


def is_online_media_path(path):
    return path.exists() and path.is_file()


def item_online_state(item):
    raw_path = media_pool_item_path(item)
    if not raw_path:
        return "missing-path"

    path = Path(raw_path).expanduser()
    if not is_online_media_path(path):
        return "offline"

    status = str(clip_property(item, "Status") or "").lower()
    if "offline" in status:
        return "offline"

    return "online"


def item_process_key(item):
    return "%s:%s" % (item_key(item), item_online_state(item))


def media_pool_signature(items):
    return tuple(sorted(item_process_key(item) for item in items))


def retry_delay(failure_count):
    exponent = min(max(0, failure_count - 1), 4)
    return min(RETRY_BASE_SECONDS * (2 ** exponent), RETRY_MAX_SECONDS)


def new_scan_state():
    return {
        "processed": set(),
        "source_cache": {},
        "signature": None,
        "last_scan_error": None,
        "failures": {},
        "retry_after": {},
    }


def replace_media_pool_item(item, output_dir_override=None, cache_dir=None, overwrite=False, quiet=False):
    raw_path = media_pool_item_path(item)
    if not raw_path:
        return None

    input_path = Path(raw_path).expanduser().resolve()
    if not is_online_media_path(input_path):
        return None

    if is_generated_remux_path(input_path):
        return None

    output_dir = cache_output_dir_for_input(input_path, cache_dir) or output_dir_for_input(input_path, output_dir_override)
    result = convert(
        input_path=input_path,
        output_dir=output_dir,
        root=input_path.parent,
        flat=True,
        overwrite=overwrite,
        dry_run=False,
        quiet=quiet,
    )
    if result.status == "skipped":
        return None
    if result.status == "error" or not result.output_path:
        raise RuntimeError(result.message or f"Could not convert {input_path}")

    replacer = getattr(item, "ReplaceClipPreserveSubClip", None) or item.ReplaceClip
    if not replacer(str(result.output_path)):
        raise RuntimeError(f"Could not replace MediaPool item with {result.output_path}")

    record_remux(result.output_path, input_path)
    log(f"Replaced MediaPool AAC item: {input_path} -> {result.output_path}")
    return result.output_path


def scan_once(args, state):
    media_pool = get_context()
    items = list(iter_media_pool_items(media_pool.GetRootFolder()))
    signature = media_pool_signature(items)
    now = time.monotonic()
    active_keys = {item_process_key(item) for item in items}
    for name in ("failures", "retry_after"):
        state[name] = {key: value for key, value in state[name].items() if key in active_keys}
    retry_due = any(deadline <= now for deadline in state["retry_after"].values())
    changed = 0

    if signature == state["signature"] and not args.retry and not retry_due:
        return 0
    state["signature"] = signature

    for item in items:
        key = item_process_key(item)
        if key in state["processed"] and not args.retry:
            continue
        if state["retry_after"].get(key, 0) > now and not args.retry:
            continue

        try:
            raw_path = media_pool_item_path(item)
            if not raw_path:
                state["processed"].add(key)
                continue

            input_path = Path(raw_path).expanduser().resolve()
            if item_online_state(item) != "online":
                state["processed"].add(key)
                log(f"Skipping offline MediaPool item: {raw_path}")
                continue

            if is_generated_remux_path(input_path):
                state["processed"].add(key)
                continue

            path_key = str(input_path)
            if state["source_cache"].get(path_key) == "non-aac":
                state["processed"].add(key)
                continue

            output_path = replace_media_pool_item(
                item,
                output_dir_override=args.output_dir,
                cache_dir=args.cache_dir,
                overwrite=args.overwrite,
                quiet=args.quiet,
            )
            state["processed"].add(key)
            state["failures"].pop(key, None)
            state["retry_after"].pop(key, None)
            if output_path:
                state["source_cache"][path_key] = "converted"
                changed += 1
            else:
                state["source_cache"][path_key] = "non-aac"
        except Exception as exc:
            failures = state["failures"].get(key, 0) + 1
            delay = retry_delay(failures)
            state["failures"][key] = failures
            state["retry_after"][key] = time.monotonic() + delay
            log(f"MediaPool watcher item failed (retry in {delay:.0f}s): {exc}")
            log(traceback.format_exc())

    return changed


def main():
    parser = argparse.ArgumentParser(
        description="Watch the Resolve Media Pool and replace AAC imports with PCM remuxes."
    )
    parser.add_argument("--interval", type=float, default=5.0, help="Polling interval in seconds")
    parser.add_argument("--once", action="store_true", help="Scan once and exit")
    parser.add_argument("--retry", action="store_true", help="Retry items already seen by this process")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite converted media")
    parser.add_argument("-o", "--output-dir", type=Path, help=f"Override output directory. Default: <source folder>/{DEFAULT_OUTPUT_SUBDIR}")
    parser.add_argument("--cache-dir", type=Path, help="Store remuxes in an external cache instead of next to source media")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if STOP_PATH.exists():
        STOP_PATH.unlink()

    log("=== Resolve AAC MediaPool Watch started ===")
    log(f"Log: {LOG_PATH}")
    log(f"Stop file: {STOP_PATH}")

    state = new_scan_state()
    resolve_seen = False
    resolve_gone = 0
    while True:
        try:
            changed = scan_once(args, state)
            state["last_scan_error"] = None
            if changed:
                log(f"MediaPool watcher replaced {changed} AAC item(s)")
        except Exception as exc:
            error = str(exc)
            if error != state["last_scan_error"]:
                log("MediaPool watcher waiting: " + error)
                log(traceback.format_exc())
                state["last_scan_error"] = error

        # Never outlive Resolve: once Resolve has been up and is gone, stop.
        if resolve_is_running():
            resolve_seen = True
            resolve_gone = 0
        elif resolve_seen:
            resolve_gone += 1
            if resolve_gone >= 3:
                log("Resolve is no longer running; MediaPool watcher exiting.")
                break

        if args.once or STOP_PATH.exists():
            break
        time.sleep(args.interval)

    log("=== Resolve AAC MediaPool Watch stopped ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
