#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from resolve_aac_import import convert, import_into_resolve, print_summary


MEDIA_EXTS = {".aac", ".m4a", ".mp4", ".mov", ".mkv"}


def load_state(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True))


def media_files(path):
    if not path.exists():
        return []
    return sorted(candidate for candidate in path.rglob("*")
                  if candidate.is_file() and candidate.suffix.lower() in MEDIA_EXTS)


def is_stable(path, wait_seconds):
    try:
        first_size = path.stat().st_size
        first_mtime = path.stat().st_mtime
        time.sleep(wait_seconds)
        second = path.stat()
    except FileNotFoundError:
        return False
    return first_size == second.st_size and first_mtime == second.st_mtime


def fingerprint(path):
    stat = path.stat()
    return f"{stat.st_size}:{int(stat.st_mtime)}"


def process_once(args, state):
    results = []
    import_paths = []

    for path in media_files(args.inbox):
        key = str(path.resolve())
        current_fingerprint = fingerprint(path)
        if state.get(key) == current_fingerprint and not args.retry:
            continue

        if not is_stable(path, args.stable_seconds):
            print(f"waiting: still copying {path}")
            continue

        result = convert(
            input_path=path.resolve(),
            output_dir=args.output.resolve(),
            root=args.inbox.resolve(),
            flat=args.flat,
            overwrite=args.overwrite,
            dry_run=False,
            quiet=args.quiet,
        )
        results.append(result)

        if result.status in {"converted", "exists"} and result.output_path:
            state[key] = current_fingerprint
            import_paths.append(result.output_path)

    if import_paths and args.do_import:
        try:
            import_into_resolve(import_paths)
        except Exception as exc:
            print(f"warning: Resolve import failed: {exc}", file=sys.stderr)

    if results:
        print_summary(results)

    return len(results)


def main():
    home = Path.home()
    parser = argparse.ArgumentParser(
        description="Watch a folder for AAC media, convert to Resolve-friendly MOV/PCM, and optionally import."
    )
    parser.add_argument("--inbox", type=Path, default=home / "Resolve AAC Inbox", help="Folder to watch")
    parser.add_argument("--output", type=Path, default=home / "Resolve AAC Imports", help="Folder for converted media")
    parser.add_argument("--state", type=Path, default=home / ".cache" / "resolve-aac-watch" / "state.json")
    parser.add_argument("--interval", type=float, default=3.0, help="Polling interval in seconds")
    parser.add_argument("--stable-seconds", type=float, default=1.0, help="Wait time used to detect completed copies")
    parser.add_argument("--once", action="store_true", help="Scan once and exit")
    parser.add_argument("--no-import", dest="do_import", action="store_false", help="Do not import into Resolve")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite converted files")
    parser.add_argument("--retry", action="store_true", help="Re-process files even if already seen")
    parser.add_argument("--flat", action="store_true", help="Put all converted files directly in output")
    parser.add_argument("--quiet", action="store_true", help="Do not print ffmpeg commands")
    parser.set_defaults(do_import=True)
    args = parser.parse_args()

    args.inbox.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)

    state = load_state(args.state)
    print(f"watching: {args.inbox}")
    print(f"output:   {args.output}")
    print("drop AAC media into the inbox folder")

    while True:
        state_changed = False
        try:
            count = process_once(args, state)
            state_changed = count > 0
        except KeyboardInterrupt:
            print("\nstopping watcher")
            break
        except subprocess.CalledProcessError as exc:
            print(f"error: command failed: {exc}", file=sys.stderr)

        if state_changed:
            save_state(args.state, state)

        if args.once:
            break
        time.sleep(args.interval)

    save_state(args.state, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
