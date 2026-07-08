#!/usr/bin/env python3

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path


MEDIA_EXTS = {".mp4", ".m4v", ".mov"}
# Directory names of the MediaPool watcher's PCM intermediates (cache dir and
# per-source `aac_remux/` copies). Files under these are Resolve inputs, not
# render outputs, and must never be remuxed to AAC.
INTERMEDIATE_DIR_NAMES = {"aac_remux", "resolve-aac-remux"}
LOG_PATH = Path("/tmp/resolve_aac_export_watch.log")
STATE_PATH = Path.home() / ".cache" / "resolve-aac-export-watch" / "state.json"
STOP_PATH = Path("/tmp/resolve_aac_export_watch.stop")


def log(message):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    if os.environ.get("RESOLVE_AAC_NO_LOG") != "1":
        with LOG_PATH.open("a") as log_file:
            log_file.write(line + "\n")
    if sys.stdout.isatty():
        print(line, flush=True)


def load_state(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def fingerprint(path):
    stat = path.stat()
    return f"{stat.st_size}:{int(stat.st_mtime)}"


def is_stable(path, stable_seconds):
    try:
        first = path.stat()
        time.sleep(stable_seconds)
        second = path.stat()
    except FileNotFoundError:
        return False
    return first.st_size == second.st_size and first.st_mtime == second.st_mtime


def iter_candidates(paths):
    for raw_path in paths:
        path = raw_path.expanduser()
        if path.is_file() and path.suffix.lower() in MEDIA_EXTS:
            yield path
            continue
        if path.is_dir():
            yield from sorted(
                candidate for candidate in path.rglob("*")
                if candidate.is_file() and candidate.suffix.lower() in MEDIA_EXTS
            )


_resolve_pids_cache = {"pids": [], "at": 0.0}


def resolve_pids():
    # Cache for ~1s so fast detect-mode polling does not spawn pgrep many times
    # per second. Resolve's PID does not change between renders.
    now = time.time()
    if now - _resolve_pids_cache["at"] < 1.0:
        return _resolve_pids_cache["pids"]

    try:
        result = subprocess.run(
            ["pgrep", "-u", str(os.getuid()), "-f", "/opt/resolve/bin/resolve"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        _resolve_pids_cache.update(pids=[], at=now)
        return []

    if result.returncode != 0:
        _resolve_pids_cache.update(pids=[], at=now)
        return []
    pids = [pid.strip() for pid in result.stdout.splitlines() if pid.strip().isdigit()]
    _resolve_pids_cache.update(pids=pids, at=now)
    return pids


def is_intermediate_path(path):
    """True for the MediaPool watcher's PCM intermediates, which Resolve opens as
    *input* media, not render outputs: the cache dir (`resolve-aac-remux`) and the
    source-folder `aac_remux/` copies. These must never be converted to AAC.
    """
    return any(part in INTERMEDIATE_DIR_NAMES for part in path.parts)


def fd_is_open_for_write(fd):
    try:
        text = (fd.parent.parent / "fdinfo" / fd.name).read_text()
    except OSError:
        return False

    for line in text.splitlines():
        if not line.startswith("flags:"):
            continue
        try:
            flags = int(line.split(":", 1)[1].strip(), 8)
        except ValueError:
            return False
        # Linux access mode bits: 0 = read-only, 1 = write-only, 2 = read/write.
        return bool(flags & 0o3)
    return False


def iter_resolve_output_paths():
    """Yield media files Resolve currently has open (render outputs).

    Resolve also opens source clips for reading while importing or playing back.
    Only write-capable handles are treated as render outputs so imported source
    clips are not modified by the export watcher.
    """
    for pid in resolve_pids():
        fd_dir = Path("/proc") / pid / "fd"
        try:
            fds = list(fd_dir.iterdir())
        except OSError:
            continue
        for fd in fds:
            try:
                target = Path(os.readlink(fd))
            except OSError:
                continue
            if " (deleted)" in str(target):
                continue
            if not fd_is_open_for_write(fd):
                continue
            if target.suffix.lower() not in MEDIA_EXTS:
                continue
            try:
                if target.exists() and target.is_file():
                    yield target.resolve()
            except OSError:
                continue


def ffprobe_audio(path):
    command = [
        "ffprobe",
        "-hide_banner",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,codec_tag_string,profile,mime_codec_string,extradata_size",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams") or []
    return streams[0] if streams else {}


def audio_metadata_is_broken(audio):
    if audio.get("codec_name") != "aac" or audio.get("codec_tag_string") != "mp4a":
        return False

    profile = str(audio.get("profile", ""))
    mime = str(audio.get("mime_codec_string", ""))
    has_extradata = "extradata_size" in audio
    return profile == "-1" or mime == "mp4a.40.0" or not has_extradata


def has_video_stream(path):
    command = [
        "ffprobe",
        "-hide_banner",
        "-v",
        "error",
        "-select_streams",
        "v",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
        str(path),
    ]
    try:
        result = subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception:
        return False
    return bool(result.stdout.strip())


def needs_aac_conversion(audio, path):
    """True if the audio should be (re-)encoded to browser-friendly AAC-LC.

    Covers FLAC, any PCM variant, and already-AAC files with broken metadata.
    Healthy AAC and other codecs are left untouched. Audio-only PCM renders
    (PCM with no video stream, e.g. WAV masters) are left as PCM.
    """
    codec = str(audio.get("codec_name", ""))
    if codec.startswith("pcm"):
        return has_video_stream(path)
    if codec == "flac":
        return True
    return audio_metadata_is_broken(audio)


def needs_conversion(path):
    try:
        audio = ffprobe_audio(path)
    except Exception as exc:
        log(f"skip probe failed: {path}: {exc}")
        return False

    return needs_aac_conversion(audio, path)


def verify_fixed(path):
    audio = ffprobe_audio(path)
    profile = str(audio.get("profile", ""))
    mime = str(audio.get("mime_codec_string", ""))
    return (
        audio.get("codec_name") == "aac"
        and audio.get("codec_tag_string") == "mp4a"
        and (profile in ("", "LC") or mime == "mp4a.40.2")
        and mime in ("", "mp4a.40.2")
        and int(audio.get("extradata_size", 0)) > 0
    )


def unique_path(path):
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}.{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find free path for {path}")


def fixed_output_path(input_path, suffix):
    if suffix.endswith(input_path.suffix):
        return input_path.with_name(input_path.name[: -len(input_path.suffix)] + suffix)
    return input_path.with_name(input_path.name + suffix)


def desktop_notify(args, title, message):
    """Best-effort desktop notification via notify-send. No-op unless --notify."""
    if not getattr(args, "notify", False):
        return
    notifier = shutil.which("notify-send")
    if not notifier:
        return
    try:
        subprocess.Popen(
            [notifier, "-a", "Resolve AAC Tools", "-i", "video-x-generic", title, message],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def convert(path, args):
    # Keep the source container: a .mov (ProRes/DNxHD) export cannot be muxed into
    # MP4, so deriving the temp extension from the input avoids ffmpeg exit 234.
    container_ext = path.suffix if path.suffix.lower() in MEDIA_EXTS else ".mp4"
    temp_path = path.with_name(f".{path.name}.resolve-aac-fix-{uuid.uuid4().hex}.tmp{container_ext}")
    output_path = path if args.replace else unique_path(fixed_output_path(path, args.suffix))

    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(path),
        "-map",
        "0:v?",
        "-map",
        "0:a?",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        args.audio_bitrate,
        "-map_metadata",
        "0",
        "-movflags",
        "+faststart",
        "-write_tmcd",
        "0",
        str(temp_path),
    ]
    log(f"fixing: {path}")
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL if args.quiet else None,
            stderr=subprocess.DEVNULL if args.quiet else None,
        )
        if not verify_fixed(temp_path):
            raise RuntimeError(f"Fixed file failed verification: {temp_path}")
    except Exception:
        temp_path.unlink(missing_ok=True)
        desktop_notify(args, "Export remux failed", path.name)
        raise

    backup_path = None
    if args.replace:
        if args.backup:
            backup_path = unique_path(path.with_name(path.name + args.backup_suffix))
            path.replace(backup_path)
        try:
            temp_path.replace(path)
        except Exception:
            if backup_path and backup_path.exists() and not path.exists():
                backup_path.replace(path)
            raise
        log(f"replaced: {path}" + (f" backup={backup_path}" if backup_path else ""))
        desktop_notify(args, "Export remuxed to AAC ✓", path.name)
        return path

    temp_path.replace(output_path)
    log(f"created: {output_path}")
    desktop_notify(args, "Export remuxed to AAC ✓", output_path.name)
    return output_path


def scan_once(args, state):
    changed = 0
    for path in iter_candidates(args.paths):
        path = path.resolve()
        if path.name.startswith("."):
            continue
        if path.name.endswith(args.backup_suffix) or path.name.endswith(args.suffix):
            continue
        try:
            stat = path.stat()
            current = fingerprint(path)
        except FileNotFoundError:
            continue
        if args.new_files_only and stat.st_mtime < args.started_at:
            continue
        if state.get(str(path)) == current and not args.retry:
            continue
        if not is_stable(path, args.stable_seconds):
            log(f"waiting: still writing {path}")
            continue
        if not needs_conversion(path):
            state[str(path)] = current
            continue
        convert(path, args)
        state[str(path)] = fingerprint(path)
        changed += 1
    return changed


def process_path(path, args, state, retry_probe_failures=False):
    path = path.resolve()
    if path.name.startswith("."):
        return False
    if path.name.endswith(args.backup_suffix) or path.name.endswith(args.suffix):
        return False
    if is_intermediate_path(path):
        return False

    try:
        stat = path.stat()
    except FileNotFoundError:
        return False
    # Only remux files produced during this watch session (real renders); never
    # touch pre-existing source/input clips that Resolve merely closed.
    if getattr(args, "started_at", 0) and stat.st_mtime < args.started_at:
        return False
    current = f"{stat.st_size}:{int(stat.st_mtime)}"

    if state.get(str(path)) == current and not args.retry:
        return False
    if not is_stable(path, args.stable_seconds):
        log(f"waiting: still writing {path}")
        return False

    if retry_probe_failures:
        try:
            broken = needs_aac_conversion(ffprobe_audio(path), path)
        except Exception as exc:
            log(f"waiting: probe failed for recent Resolve output {path}: {exc}")
            return False
    else:
        broken = needs_conversion(path)

    if not broken:
        state[str(path)] = current
        return False

    convert(path, args)
    state[str(path)] = fingerprint(path)
    return True


def scan_detected_resolve_outputs_once(args, state, runtime):
    active = runtime.setdefault("active", {})
    closed = runtime.setdefault("closed", {})
    open_paths = {
        str(path)
        for path in iter_resolve_output_paths()
        if not is_intermediate_path(path)
    }

    for raw_path in sorted(open_paths):
        if raw_path not in active:
            log(f"detected Resolve output: {raw_path}")
        active[raw_path] = time.time()
        closed.pop(raw_path, None)

    for raw_path in list(active):
        if raw_path in open_paths:
            continue
        closed.setdefault(raw_path, time.time())

    changed = 0
    now = time.time()
    for raw_path, closed_at in list(closed.items()):
        if raw_path in open_paths:
            continue
        if now - closed_at < args.closed_grace_seconds:
            continue

        path = Path(raw_path)
        if not path.exists():
            active.pop(raw_path, None)
            closed.pop(raw_path, None)
            continue

        try:
            if process_path(path, args, state, retry_probe_failures=True):
                changed += 1
                active.pop(raw_path, None)
                closed.pop(raw_path, None)
            elif str(path) in state:
                active.pop(raw_path, None)
                closed.pop(raw_path, None)
        except Exception as exc:
            log(f"error processing detected Resolve output {path}: {exc}")
            try:
                state[str(path)] = fingerprint(path)
            except OSError:
                pass
            active.pop(raw_path, None)
            closed.pop(raw_path, None)
            changed += 1

    return changed


def parse_args():
    parser = argparse.ArgumentParser(
        description="Watch rendered Resolve MP4/MOV files and repair AAC metadata automatically."
    )
    parser.add_argument("paths", nargs="*", type=Path, default=[Path.home() / "Videos"])
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--stable-seconds", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--retry", action="store_true")
    parser.add_argument("--replace", action="store_true", help="Replace the original file after verification.")
    parser.add_argument("--no-backup", dest="backup", action="store_false", help="Do not keep a backup when replacing.")
    parser.add_argument("--backup-suffix", default=".bad-aac-backup.mp4")
    parser.add_argument("--suffix", default=".fixed.mp4")
    parser.add_argument("--audio-bitrate", default="192k")
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    parser.add_argument("--new-files-only", action="store_true", help="Only process files modified after this watcher starts.")
    parser.add_argument("--detect-resolve-outputs", action="store_true", help="Detect render output files from Resolve's open file handles instead of scanning folders.")
    parser.add_argument("--closed-grace-seconds", type=float, default=3.0, help="Wait this long after Resolve closes an output file before repairing it.")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--notify", action="store_true", help="Send a desktop notification (notify-send) when a remux starts and finishes.")
    parser.set_defaults(backup=True)
    return parser.parse_args()


def main():
    args = parse_args()
    args.started_at = time.time()
    try:
        STOP_PATH.unlink()
    except FileNotFoundError:
        pass
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe are required")

    state = load_state(args.state)
    log("=== Resolve AAC Export Watch started ===")
    if args.detect_resolve_outputs:
        log("detecting Resolve output files from /proc")
    else:
        log("paths: " + ", ".join(str(path.expanduser()) for path in args.paths))
    log(f"mode: {'replace' if args.replace else 'sidecar'}")

    runtime = {}
    while True:
        try:
            if args.detect_resolve_outputs:
                changed = scan_detected_resolve_outputs_once(args, state, runtime)
            else:
                changed = scan_once(args, state)
            if changed:
                save_state(args.state, state)
        except KeyboardInterrupt:
            break
        except Exception as exc:
            log(f"error: {exc}")

        if args.once or STOP_PATH.exists():
            break
        time.sleep(args.interval)

    save_state(args.state, state)
    log("=== Resolve AAC Export Watch stopped ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
