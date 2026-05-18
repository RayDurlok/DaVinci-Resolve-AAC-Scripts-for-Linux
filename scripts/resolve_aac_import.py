#!/usr/bin/env python3

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


RESOLVE_SCRIPT_MODULE = "/opt/resolve/Developer/Scripting/Modules/DaVinciResolveScript.py"
MEDIA_EXTS = {".aac", ".m4a", ".mp4", ".mov", ".mkv"}


class JobResult:
    def __init__(self, input_path: Path, output_path: Optional[Path], status: str, message: str = ""):
        self.input_path = input_path
        self.output_path = output_path
        self.status = status
        self.message = message


def command_text(command):
    return " ".join(str(part) for part in command)


def run_json(command):
    result = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return json.loads(result.stdout)


def run(command, quiet=False):
    if not quiet:
        print("+ " + command_text(command))
    subprocess.run(command, check=True)


def ffprobe(path):
    return run_json([
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_entries",
        "format=format_name,duration:stream=index,codec_type,codec_name,codec_tag_string,sample_rate,channels",
        str(path),
    ])


def aac_audio_streams(probe):
    return [
        stream for stream in probe.get("streams", [])
        if stream.get("codec_type") == "audio" and stream.get("codec_name") == "aac"
    ]


def has_video(probe):
    return any(stream.get("codec_type") == "video" for stream in probe.get("streams", []))


def audio_streams(probe):
    return [
        stream for stream in probe.get("streams", [])
        if stream.get("codec_type") == "audio"
    ]


def collect_inputs(paths):
    files = []
    seen = set()
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if path.is_dir():
            candidates = sorted(candidate for candidate in path.rglob("*")
                                if candidate.is_file() and candidate.suffix.lower() in MEDIA_EXTS)
        elif path.is_file():
            candidates = [path]
        else:
            print(f"warning: skipping missing path: {path}", file=sys.stderr)
            continue

        for candidate in candidates:
            if candidate not in seen:
                files.append(candidate)
                seen.add(candidate)

    return files


def common_root(paths):
    if not paths:
        return Path.cwd()
    if len(paths) == 1:
        return paths[0].parent
    try:
        return Path(*Path.commonpath(paths))
    except AttributeError:
        import os
        return Path(os.path.commonpath([str(path) for path in paths]))


def output_digest(input_path):
    digest = hashlib.sha1(str(input_path).encode("utf-8")).hexdigest()[:8]
    return digest


def safe_output_name(input_path):
    return f"{input_path.stem}_remux_{output_digest(input_path)}.mov"


def output_path_for(input_path, output_dir, root, flat):
    if flat:
        return output_dir / safe_output_name(input_path)

    try:
        relative_parent = input_path.parent.relative_to(root)
    except ValueError:
        relative_parent = Path()
    return output_dir / relative_parent / safe_output_name(input_path)


def build_ffmpeg_command(input_path, output_path, probe, overwrite):
    command = ["ffmpeg", "-y" if overwrite else "-n", "-hide_banner", "-i", str(input_path)]

    if has_video(probe):
        command.extend(["-map", "0:v?", "-map", "0:a?", "-map", "0:s?"])
        command.extend(["-c:v", "copy", "-c:s", "copy"])
    else:
        command.extend(["-map", "0:a?"])

    for audio_index, stream in enumerate(audio_streams(probe)):
        codec = "pcm_s24le" if stream.get("codec_name") == "aac" else "copy"
        command.extend([f"-c:a:{audio_index}", codec])

    command.extend(["-movflags", "+faststart", str(output_path)])
    return command


def convert(input_path, output_dir, root, flat, overwrite, dry_run, quiet):
    output_path = output_path_for(input_path, output_dir, root, flat)
    if output_path.exists() and not overwrite:
        return JobResult(input_path, output_path, "exists", "already converted")

    try:
        probe = ffprobe(input_path)
    except subprocess.CalledProcessError as exc:
        return JobResult(input_path, None, "error", f"ffprobe failed: {exc}")

    streams = aac_audio_streams(probe)
    if not streams:
        return JobResult(input_path, None, "skipped", "no AAC audio")

    command = build_ffmpeg_command(input_path, output_path, probe, overwrite)
    if dry_run:
        return JobResult(input_path, output_path, "dry-run", command_text(command))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        run(command, quiet=quiet)
    except subprocess.CalledProcessError as exc:
        return JobResult(input_path, output_path, "error", f"ffmpeg failed: {exc}")

    return JobResult(input_path, output_path, "converted", f"{len(streams)} AAC audio stream(s)")


def get_resolve():
    module_dir = str(Path(RESOLVE_SCRIPT_MODULE).parent)
    os.environ.setdefault("RESOLVE_SCRIPT_API", "/opt/resolve/Developer/Scripting")
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", "/opt/resolve/libs/Fusion/fusionscript.so")
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)

    module = importlib.import_module("DaVinciResolveScript")
    if not hasattr(module, "scriptapp"):
        raise RuntimeError("Could not load DaVinciResolveScript module")
    return module.scriptapp("Resolve")


def import_into_resolve(paths):
    resolve = get_resolve()
    if not resolve:
        raise RuntimeError("Could not connect to Resolve. Is Resolve running and scripting enabled?")

    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject() if project_manager else None
    if not project:
        raise RuntimeError("Resolve has no current project")

    media_pool = project.GetMediaPool()
    imported = media_pool.ImportMedia([str(path) for path in paths])
    print(f"imported {len(imported) if imported else 0} item(s) into Resolve")


def print_summary(results):
    counts = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1

    print("\nsummary:")
    for status in ("converted", "exists", "skipped", "dry-run", "error"):
        if status in counts:
            print(f"  {status}: {counts[status]}")

    print("\noutputs:")
    for result in results:
        if result.output_path:
            print(f"  {result.status}: {result.output_path}")
        else:
            print(f"  {result.status}: {result.input_path} ({result.message})")


def main():
    parser = argparse.ArgumentParser(
        description="Convert AAC media to Resolve-friendly MOV/PCM and optionally import it."
    )
    parser.add_argument("paths", nargs="+", help="Input files or folders")
    parser.add_argument(
        "-o",
        "--output-dir",
        default="Resolve AAC Imports",
        help="Output directory. Default: ./Resolve AAC Imports",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite converted files")
    parser.add_argument("--import", dest="do_import", action="store_true", help="Import converted files into the current Resolve project")
    parser.add_argument("--dry-run", action="store_true", help="Show planned conversions without writing files")
    parser.add_argument("--flat", action="store_true", help="Put all converted files directly in the output directory")
    parser.add_argument("--quiet", action="store_true", help="Do not print ffmpeg commands")
    args = parser.parse_args()

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("ffmpeg and ffprobe must be available in PATH", file=sys.stderr)
        return 2

    input_files = collect_inputs(args.paths)
    if not input_files:
        print("no input media found", file=sys.stderr)
        return 1

    root = common_root(input_files)
    output_dir = Path(args.output_dir).expanduser().resolve()
    results = [
        convert(path, output_dir, root, args.flat, args.overwrite, args.dry_run, args.quiet)
        for path in input_files
    ]

    import_paths = [
        result.output_path for result in results
        if result.output_path and result.status in {"converted", "exists"}
    ]
    if args.do_import and import_paths and not args.dry_run:
        import_into_resolve(import_paths)

    print_summary(results)
    return 1 if any(result.status == "error" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
