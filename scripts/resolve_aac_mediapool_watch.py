#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys
import time
import traceback
from collections import deque
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from resolve_aac_import import convert, get_resolve
from resolve_aac_timeline import (
    DEFAULT_OUTPUT_SUBDIR,
    is_generated_remux_path,
    iter_media_pool_items,
    cache_output_dir_for_input,
    output_dir_for_input,
    record_remux,
)


STOP_PATH = Path("/tmp/resolve_aac_mediapool_watch.stop")
LOG_PATH = Path("/tmp/resolve_aac_mediapool_watch.log")
RETRY_BASE_SECONDS = 5.0
RETRY_MAX_SECONDS = 60.0
DEFAULT_MAX_RSS_MIB = 256
DEFAULT_BATCH_SIZE = 2
DEFAULT_FAST_SCAN_ITEMS = 32
DEFAULT_BACKGROUND_ITEMS = 24
DEFAULT_BACKGROUND_RESCAN_SECONDS = 30.0


def log(message):
    if os.environ.get("RESOLVE_AAC_NO_LOG"):
        return
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with LOG_PATH.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(f"[{timestamp}] {message}\n")


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


def media_pool_item_path(item):
    """Read only the path property.

    Resolve's Linux scripting bridge leaks a large native allocation whenever
    GetClipProperty() is called without a key. A polling watcher must therefore
    never use the compatibility fallback from the one-shot timeline helpers.
    """
    try:
        return item.GetClipProperty("File Path") or ""
    except Exception:
        return ""


def direct_clip_property(item, key):
    try:
        return item.GetClipProperty(key) or ""
    except Exception:
        return ""


def item_key(item, raw_path=None):
    try:
        media_id = item.GetMediaId()
    except Exception:
        media_id = ""

    try:
        path = media_pool_item_path(item) if raw_path is None else raw_path
        return "%s:%s" % (media_id, path)
    except Exception:
        return media_id or str(id(item))


def is_online_media_path(path):
    return path.exists() and path.is_file()


def item_online_state(item, raw_path=None):
    if raw_path is None:
        raw_path = media_pool_item_path(item)
    if not raw_path:
        return "missing-path"

    path = Path(raw_path).expanduser()
    if not is_online_media_path(path):
        return "offline"

    status = str(direct_clip_property(item, "Status")).lower()
    if "offline" in status:
        return "offline"

    return "online"


def item_process_key(item, raw_path=None, online_state=None):
    if online_state is None:
        online_state = item_online_state(item, raw_path)
    return "%s:%s" % (item_key(item, raw_path), online_state)


def scan_record(item):
    """Read each Resolve property at most once for this scan."""
    raw_path = media_pool_item_path(item)
    online_state = item_online_state(item, raw_path)
    key = item_process_key(item, raw_path, online_state)
    return item, key, raw_path, online_state


def media_pool_signature(items):
    return tuple(sorted(item_process_key(item) for item in items))


def retry_delay(failure_count):
    exponent = min(max(0, failure_count - 1), 4)
    return min(RETRY_BASE_SECONDS * (2 ** exponent), RETRY_MAX_SECONDS)


def current_rss_mib():
    try:
        resident_pages = int(Path("/proc/self/statm").read_text().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
    except (OSError, ValueError, IndexError):
        return 0.0


def recycle_if_memory_high(max_rss_mib):
    if max_rss_mib <= 0:
        return False
    rss_mib = current_rss_mib()
    if rss_mib < max_rss_mib:
        return False

    log(
        f"MediaPool watcher reached {rss_mib:.0f} MiB RSS "
        f"(limit {max_rss_mib} MiB); recycling process."
    )
    os.execv(sys.executable, [sys.executable, *sys.argv])
    return True


def new_scan_state():
    return {
        "processed": set(),
        "source_cache": {},
        "signature": None,
        "known_keys": None,
        "scan_count": 0,
        "background_root": None,
        "background_folders": deque(),
        "background_items": deque(),
        "background_next_cycle": 0.0,
        "last_scan_error": None,
        "failures": {},
        "retry_after": {},
    }


def finish_scan(state, item_count, changed, started_at, offline=0):
    duration = time.monotonic() - started_at
    if state["scan_count"] == 0 or changed or duration >= 2.0:
        log(
            f"MediaPool scan complete: {item_count} item(s), "
            f"{changed} remuxed, {offline} offline, {duration:.2f}s"
        )
    state["scan_count"] += 1
    return changed


def folder_identity(folder):
    try:
        unique_id = folder.GetUniqueId()
    except Exception:
        unique_id = ""
    if unique_id:
        return str(unique_id)
    try:
        return f"{folder.GetName()}:{folder}"
    except Exception:
        return str(folder)


def collect_incremental_items(media_pool, state, fast_limit, background_limit, rescan_seconds):
    """Return current-bin newest clips first, plus a bounded project backlog chunk."""
    root = media_pool.GetRootFolder()
    try:
        current = media_pool.GetCurrentFolder() or root
    except Exception:
        current = root

    try:
        current_clips = list(current.GetClipList() or [])
    except Exception:
        current_clips = []
    fast_items = list(reversed(current_clips[-max(0, fast_limit):]))

    marker = folder_identity(root)
    if marker != state["background_root"]:
        state["background_root"] = marker
        state["background_folders"].clear()
        state["background_items"].clear()
        state["background_next_cycle"] = 0.0

    now = time.monotonic()
    if (
        not state["background_folders"]
        and not state["background_items"]
        and now >= state["background_next_cycle"]
    ):
        state["background_folders"].append(root)

    background = []
    while len(background) < max(0, background_limit):
        if state["background_items"]:
            background.append(state["background_items"].popleft())
            continue

        if not state["background_folders"]:
            state["background_next_cycle"] = now + max(1.0, rescan_seconds)
            break

        folder = state["background_folders"].popleft()
        try:
            state["background_folders"].extend(folder.GetSubFolderList() or [])
            state["background_items"].extend(folder.GetClipList() or [])
        except Exception:
            continue

    # A clip can be in both the fast lane and the background queue. Object
    # identity is sufficient for de-duplicating within this one API pass.
    seen = set()
    result = []
    for item in [*fast_items, *background]:
        marker = id(item)
        if marker not in seen:
            seen.add(marker)
            result.append(item)
    return result


def replace_media_pool_item(
    item,
    output_dir_override=None,
    cache_dir=None,
    overwrite=False,
    quiet=False,
    raw_path=None,
):
    if raw_path is None:
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
    started_at = time.monotonic()
    media_pool = get_context()
    incremental = hasattr(args, "background_items")
    if incremental:
        items = collect_incremental_items(
            media_pool,
            state,
            fast_limit=args.fast_scan_items,
            background_limit=args.background_items,
            rescan_seconds=args.background_rescan_seconds,
        )
    else:
        items = list(iter_media_pool_items(media_pool.GetRootFolder()))
    records = [scan_record(item) for item in items]
    signature = tuple(sorted(record[1] for record in records))
    now = time.monotonic()
    active_keys = {record[1] for record in records}
    previous_keys = state.get("known_keys")
    state["known_keys"] = (previous_keys or set()) | active_keys if incremental else active_keys
    if not incremental:
        for name in ("failures", "retry_after"):
            state[name] = {key: value for key, value in state[name].items() if key in active_keys}
    retry_due = any(deadline <= now for deadline in state["retry_after"].values())
    pending = any(key not in state["processed"] for key in active_keys)
    changed = 0
    offline = 0

    if signature == state["signature"] and not args.retry and not retry_due and not pending:
        return finish_scan(state, len(records), 0, started_at)
    state["signature"] = signature

    # The first project scan can contain hundreds of old clips. Once that scan
    # has begun, put clips imported since the previous pass first so a backlog
    # cannot hide a fresh drag-and-drop for minutes.
    if previous_keys is not None:
        records.sort(key=lambda record: record[1] in previous_keys)

    batch_size = max(0, int(getattr(args, "batch_size", 0)))
    for item, key, raw_path, online_state in records:
        if key in state["processed"] and not args.retry:
            continue
        if state["retry_after"].get(key, 0) > now and not args.retry:
            continue

        try:
            if not raw_path:
                state["processed"].add(key)
                continue

            input_path = Path(raw_path).expanduser().resolve()
            if online_state != "online":
                state["processed"].add(key)
                offline += 1
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
                raw_path=raw_path,
            )
            state["processed"].add(key)
            state["failures"].pop(key, None)
            state["retry_after"].pop(key, None)
            if output_path:
                state["source_cache"][path_key] = "converted"
                changed += 1
                if batch_size and changed >= batch_size:
                    break
            else:
                state["source_cache"][path_key] = "non-aac"
        except Exception as exc:
            failures = state["failures"].get(key, 0) + 1
            delay = retry_delay(failures)
            state["failures"][key] = failures
            state["retry_after"][key] = time.monotonic() + delay
            log(f"MediaPool watcher item failed (retry in {delay:.0f}s): {exc}")
            log(traceback.format_exc())

    return finish_scan(state, len(records), changed, started_at, offline)


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
    parser.add_argument(
        "--max-rss-mib",
        type=int,
        default=DEFAULT_MAX_RSS_MIB,
        help="Recycle the watcher at this RSS limit. Set to 0 to disable.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Maximum AAC conversions before rescanning for newly imported clips. Set to 0 for unlimited.",
    )
    parser.add_argument(
        "--fast-scan-items",
        type=int,
        default=DEFAULT_FAST_SCAN_ITEMS,
        help="Newest clips checked in the current MediaPool folder on every pass.",
    )
    parser.add_argument(
        "--background-items",
        type=int,
        default=DEFAULT_BACKGROUND_ITEMS,
        help="Existing project clips checked per background pass.",
    )
    parser.add_argument(
        "--background-rescan-seconds",
        type=float,
        default=DEFAULT_BACKGROUND_RESCAN_SECONDS,
        help="Delay before beginning another full incremental project pass.",
    )
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
        changed = 0
        try:
            changed = scan_once(args, state)
            state["last_scan_error"] = None
            if changed:
                log(f"MediaPool watcher replaced {changed} AAC item(s)")
            recycle_if_memory_high(args.max_rss_mib)
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
        # Re-enumerate quickly after conversions so newly imported clips can
        # jump ahead of remaining project backlog.
        time.sleep(0.25 if changed else args.interval)

    log("=== Resolve AAC MediaPool Watch stopped ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
