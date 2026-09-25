#!/usr/bin/env python3
"""Opt-in native AAC installation. Downloads/builds never run as root."""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import mmap
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

PATCH_VERSION = "v0.1.1"
PATCH_URL = ("https://github.com/josephg/resolve-aacfix/releases/download/"
             f"{PATCH_VERSION}/resolve-aacfix-{PATCH_VERSION}-linux-x86_64.tar.gz")
PATCH_SHA256 = "0beedbdd506404bafb140219e5404a417af9f3c3297db2f70ef0569b018c45e0"
FFMPEG_URL = "https://ffmpeg.org/releases/ffmpeg-6.0.1.tar.xz"
FFMPEG_SHA256 = "9b16b8731d78e596b4be0d720428ca42df642bb2d78342881ff7f5bc29fc9623"
RESOLVE_ROOT = Path("/opt/resolve")
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "resolve-aac-tools/native-aac"
PACKAGE_DIR = DATA_DIR / PATCH_VERSION
PLUGIN_BUNDLE = "aac_ffmpeg6_experiment.dvcp.bundle"
PLUGIN_FILE = "aac_ffmpeg6_experiment.dvcp"
LEGACY_BUNDLE = "aac_encoder_plugin.dvcp.bundle"
BUILD_TOOLS = ("clang++", "cc", "make", "readelf", "sha256sum", "pkexec")
PROGRESS_PREFIX = "NATIVE_AAC_PROGRESS "


def progress(step, state="running", message=""):
    print(PROGRESS_PREFIX + json.dumps({"step": step, "state": state, "message": message}), flush=True)


def run(command, **kwargs):
    print("Running: " + " ".join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), check=True, **kwargs)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_verified(url, target, expected):
    target = Path(target)
    if target.is_file() and sha256(target) == expected:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        print("Downloading " + url, flush=True)
        with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        if sha256(temporary) != expected:
            raise RuntimeError("Download checksum mismatch; refusing to extract or execute it.")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def extract_verified(archive, destination):
    if not hasattr(tarfile, "data_filter"):
        raise RuntimeError("Native AAC needs a Python version with safe tar extraction (Python 3.12+ recommended).")
    with tarfile.open(archive) as source:
        source.extractall(destination, filter="data")


def resolve_processes(root=RESOLVE_ROOT, proc=Path("/proc")):
    target = root / "bin/resolve"
    result = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            executable = os.readlink(entry / "exe").removesuffix(" (deleted)")
            if executable == str(target):
                result.append(int(entry.name))
        except (OSError, ValueError):
            continue
    return result


def require_closed(root=RESOLVE_ROOT):
    if resolve_processes(root):
        raise RuntimeError("Close Resolve first. No changes were made to the running application.")


@contextmanager
def operation_lock():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with (DATA_DIR / "operation.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another native AAC operation or Resolve update is already running.")
        yield


def operation_in_progress():
    try:
        with operation_lock():
            return False
    except RuntimeError:
        return True


def resolve_info(root=RESOLVE_ROOT):
    try:
        with (root / "bin/resolve").open("rb") as source:
            with mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data:
                match = re.search(rb"\b(\d+\.\d+\.\d+)\.\d+_(studio|free)\b", data)
                if match:
                    return match[1].decode(), match[2].decode()
    except (OSError, ValueError):
        pass
    return None, None


def supported(version, edition):
    return bool(version and version.split(".")[0] == "21" and edition == "studio"
                and sys.platform == "linux" and platform.machine() == "x86_64")


def dependency_command():
    for manager, arguments in (
        ("dnf", ["install", "-y", "clang", "gcc", "gcc-c++", "make", "binutils"]),
        ("apt-get", ["install", "-y", "clang", "build-essential", "binutils"]),
        ("pacman", ["-S", "--needed", "--noconfirm", "clang", "gcc", "make", "binutils"]),
        ("zypper", ["--non-interactive", "install", "clang", "gcc", "gcc-c++", "make", "binutils"]),
    ):
        if shutil.which(manager) and shutil.which("pkexec"):
            return ["pkexec", shutil.which(manager), *arguments]
    return None


def find_package():
    for candidate in (PACKAGE_DIR, Path.home() / ".local/share/resolve-aacfix" / PATCH_VERSION):
        if (candidate / "aac-fix").is_file():
            return candidate
    return None


def native_status(root=RESOLVE_ROOT):
    version, edition = resolve_info(root)
    state = {"version": version, "edition": edition, "supported": supported(version, edition),
             "missing_tools": [name for name in BUILD_TOOLS if not shutil.which(name)],
             "can_install_dependencies": dependency_command() is not None,
             "import_active": False, "import_patched": False, "status_verified": False,
             "export_installed": (root / "IOPlugins" / PLUGIN_BUNDLE /
                 "Contents/Linux-x86-64" / PLUGIN_FILE).is_file(),
             "details": "Patch status unknown. Install/check the native components to verify."}
    package = find_package()
    if package and shutil.which("readelf"):
        result = subprocess.run(["bash", str(package / "aac-fix"), "status", str(root)],
                                capture_output=True, text=True, timeout=60)
        details = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout + result.stderr)
        state["details"] = details.strip()
        state["status_verified"] = result.returncode == 0
        state["import_patched"] = bool(re.search(r"binary:\s+PATCHED", details))
        state["import_active"] = (result.returncode == 0 and "AAC support: ACTIVE" in details
                                  and "mixed library set" not in details)
    try:
        update = json.loads((DATA_DIR / "update-state.json").read_text())
        if update.get("phase") in ("incomplete", "unsupported", "removing", "installing", "patching"):
            state["update_message"] = str(update.get("message", ""))
            state["details"] += "\nLast Resolve update: " + state["update_message"]
    except (OSError, ValueError, AttributeError):
        pass
    return state


def prepare_package():
    standalone = Path.home() / ".local/share/resolve-aacfix" / f"resolve-aacfix-{PATCH_VERSION}-linux-x86_64.tar.gz"
    cached = DATA_DIR / "resolve-aacfix.tar.gz"
    if not cached.exists() and standalone.is_file() and sha256(standalone) == PATCH_SHA256:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(standalone, cached)
    archive = download_verified(PATCH_URL, DATA_DIR / "resolve-aacfix.tar.gz", PATCH_SHA256)
    # Re-extract the verified archive before executing privileged installer code.
    with tempfile.TemporaryDirectory(dir=DATA_DIR, prefix="patch-stage-") as temp:
        extract_verified(archive, temp)
        candidates = list(Path(temp).rglob("aac-fix"))
        if len(candidates) != 1:
            raise RuntimeError("Unexpected patch archive layout.")
        source = candidates[0].parent
        for required in ("LICENSE", "THIRD-PARTY.md", "aac-patch-tree", "SHA256SUMS"):
            if not (source / required).is_file():
                raise RuntimeError("Incomplete upstream release: " + required)
        if PACKAGE_DIR.exists():
            shutil.rmtree(PACKAGE_DIR)
        shutil.copytree(source, PACKAGE_DIR, symlinks=True)
    return PACKAGE_DIR


def source_dir():
    here = Path(__file__).resolve().parent
    for candidate in (here / "native-aac", here.parent / "native-aac"):
        if (candidate / "audio_encoder.cpp").is_file():
            return candidate
    raise RuntimeError("Native export sources are missing. Reinstall the complete toolkit package.")


def build_export(package, work):
    source = source_dir()
    archive = download_verified(FFMPEG_URL, DATA_DIR / "ffmpeg-6.0.1.tar.xz", FFMPEG_SHA256)
    extract_verified(archive, work)
    progress("download", "done", "Downloads verified and extracted.")
    progress("build", message="Building the export plugin. This can take a few minutes.")
    headers = work / "ffmpeg-6.0.1"
    run([headers / "configure", "--disable-everything", "--disable-programs", "--disable-doc",
         "--disable-x86asm"], cwd=headers)
    output = work / PLUGIN_FILE
    run(["clang++", "-std=c++11", "-O2", "-fPIC", "-shared",
         "-ffile-prefix-map=" + str(work) + "=.",
         "-ffile-prefix-map=" + str(source) + "=native-aac",
         "-I" + str(source), "-I" + str(source / "include"), "-I" + str(headers),
         source / "plugin.cpp", source / "audio_encoder.cpp",
         source / "wrapper/host_api.cpp", source / "wrapper/plugin_api.cpp",
         "-L" + str(package / "prebuilt/ffmpeg-aac"),
         "-Wl,-rpath,/opt/resolve/libs", "-Wl,-z,defs",
         "-l:libavcodec.so.60.3.100", "-l:libavutil.so.58.2.100", "-o", output])
    return output


def privileged(action, payload):
    step = {"install-patch": "import", "install-export": "export", "uninstall": "restore"}[action]
    progress(step, "waiting", "Approve the administrator dialog to continue.")
    run(["pkexec", "bash", source_dir() / "privileged.sh", action, payload])


def install():
    progress("check", message="Checking Resolve, its version and build tools.")
    require_closed()
    version, edition = resolve_info()
    if not supported(version, edition):
        raise RuntimeError("Native AAC requires Resolve Studio 21.x on Linux x86-64. Use Legacy on other versions.")
    missing = [name for name in BUILD_TOOLS if not shutil.which(name)]
    if missing:
        raise RuntimeError("Missing native-build dependencies: " + ", ".join(missing) +
                           ". Install clang, a C/C++ development toolchain, make, binutils and polkit, then retry.")
    if (RESOLVE_ROOT / "IOPlugins" / LEGACY_BUNDLE).exists():
        raise RuntimeError("Remove the Resolve-20 AAC export plugin in Legacy options first; it is not compatible with Resolve 21.")
    progress("check", "done")
    progress("download", message="Downloading or reusing cached files; checking their integrity.")
    package = prepare_package()
    with tempfile.TemporaryDirectory(dir=DATA_DIR, prefix="export-build-") as temp:
        binary = build_export(package, Path(temp))
        progress("build", "done")
        progress("import", message="Checking the import patch before applying changes.")
        require_closed()
        if not native_status()["import_active"]:
            privileged("install-patch", package)
        if not native_status()["import_active"]:
            raise RuntimeError("Native import is not active. Export was not installed; inspect the upstream diagnostics.")
        progress("import", "done", "Import patch verified.")
        require_closed()
        privileged("install-export", binary)
        progress("export", "done")
    progress("verify", message="Verifying that import and export are both installed.")
    state = native_status()
    if not state["import_active"] or not state["export_installed"]:
        raise RuntimeError("Native AAC activation is incomplete. Both import and export must be present; use repair or disable.")
    progress("verify", "done")
    print("Native import and experimental AAC-LC export installed. Restart Resolve.", flush=True)


def uninstall():
    progress("check", message="Checking that Resolve is closed.")
    require_closed()
    progress("check", "done")
    progress("download", message="Preparing the verified restore tools.")
    package = prepare_package()
    progress("download", "done")
    privileged("uninstall", package)
    progress("restore", "done")
    progress("verify", message="Verifying removal of both native components.")
    state = native_status()
    if state["import_active"] or state["export_installed"]:
        raise RuntimeError("Native AAC removal is incomplete. Inspect the diagnostics before restarting Resolve.")
    progress("verify", "done")
    print("Native patch removed. Upstream backups restored; export plugin kept disabled.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "install", "uninstall", "install-deps"))
    args = parser.parse_args()
    if args.action == "status":
        print(json.dumps(native_status()))
        return
    with operation_lock():
        if args.action == "install-deps":
            progress("dependencies", message="Installing build tools. Approve the system dialog if prompted.")
            command = dependency_command()
            if not command:
                raise RuntimeError("Install clang, a C/C++ toolchain, make, binutils and polkit with your package manager.")
            run(command)
            progress("dependencies", "done")
        else:
            {"install": install, "uninstall": uninstall}[args.action]()


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as exc:
        print("Native AAC: " + str(exc), file=sys.stderr, flush=True)
        raise SystemExit(1)
