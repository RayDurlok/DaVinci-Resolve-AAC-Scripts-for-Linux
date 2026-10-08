#!/usr/bin/env python3
"""Build and load the opt-in, build-guarded native dialog extension."""
import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile

from resolve_aac_config import load_config

SCRIPT_DIR = Path(__file__).resolve().parent
SOURCES = ("dialog_hook.cpp", "relink_bridge.cpp", "relink_bridge.h",
           "deliver_bridge.cpp", "deliver_bridge.h")
LIBRARIES = ("libQt5Widgets.so.5", "libQt5Gui.so.5", "libQt5Core.so.5")


def enabled():
    return bool(load_config().get("intercept_deliver_browse", False))


def source_dir():
    for directory in (SCRIPT_DIR / "native-dialogs", SCRIPT_DIR.parent / "native-dialogs"):
        if all((directory / name).is_file() for name in SOURCES):
            return directory
    raise RuntimeError("Native dialog sources are missing; reinstall the toolkit.")


def build_tools():
    compiler = shutil.which("c++") or shutil.which("clang++")
    pkg_config = shutil.which("pkg-config")
    if not compiler or not pkg_config:
        raise RuntimeError("Native relink needs a C++ compiler, pkg-config and Qt5 development headers.")
    flags = subprocess.run([pkg_config, "--cflags", "Qt5Widgets"], capture_output=True,
                           text=True, check=True, timeout=10).stdout
    return compiler, shlex.split(flags)


def cache_dir():
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "resolve-aac-tools/native-dialogs"


def clean_helper_env(environment):
    environment = dict(environment)
    for name in ("LD_PRELOAD", "LD_LIBRARY_PATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORMTHEME",
                 "PYTHONHOME", "PYTHONPATH"):
        environment.pop(name, None)
    return environment


def prepare_library(resolve=Path("/opt/resolve/bin/resolve")):
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("Native dialog extension requires Linux x86-64.")
    directory = source_dir()
    libs = resolve.parent.parent / "libs"
    digest = hashlib.sha256(b"resolve-native-dialogs-build-v1")
    for name in SOURCES:
        digest.update(name.encode())
        digest.update((directory / name).read_bytes())
    for name in LIBRARIES:
        library = libs / name
        stat = library.stat()
        digest.update(str((str(library), stat.st_size, stat.st_mtime_ns)).encode())
    cache = cache_dir()
    # LD_PRELOAD cannot encode paths containing separators or whitespace.
    if any(char.isspace() or char == ":" for char in str(cache)):
        raise RuntimeError("Native dialog cache path cannot contain spaces or colons.")
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = cache / (digest.hexdigest() + ".so")
    with (cache / "build.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.is_file():
            return target
        compiler, flags = build_tools()
        fd, temporary = tempfile.mkstemp(prefix="build-", suffix=".so", dir=cache)
        os.close(fd)
        try:
            command = [compiler, "-std=c++17", "-fPIC", "-pthread", "-shared",
                       "-DQT_NO_VERSION_TAGGING", *flags]
            command += [str(directory / name) for name in SOURCES if name.endswith(".cpp")]
            command += ["-L" + str(libs), "-Wl,-rpath," + str(libs), "-Wl,-z,defs",
                        *("-l:" + name for name in LIBRARIES), "-ldl", "-o", temporary]
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=120,
                           env=clean_helper_env(os.environ))
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return target


def launch_environment(environment=None):
    environment = dict(os.environ if environment is None else environment)
    # An inherited flag must not override the user's disabled setting.
    environment.pop("RESOLVE_TOOLKIT_NATIVE_DIALOGS", None)
    if not enabled():
        return environment
    try:
        library = prepare_library()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Native dialog extension unavailable; using existing dialogs: {exc}", file=sys.stderr)
        return environment
    environment["LD_PRELOAD"] = " ".join(filter(None, [environment.get("LD_PRELOAD"), str(library)]))
    environment["RESOLVE_TOOLKIT_NATIVE_DIALOGS"] = "1"
    environment["RESOLVE_NATIVE_DELIVER_HELPER"] = str(Path(__file__).resolve())
    environment["RESOLVE_NATIVE_DELIVER_PYTHON"] = sys.executable
    return environment


def deliver_picker():
    import set_render_location as srl
    directory = cache_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "deliver.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        try:
            # Open the chooser before accessing Resolve; its Browse action can
            # unwind and release any modal state before we apply the selection.
            return srl.main([])
        except Exception as exc:
            srl.notify(f"Could not set the render destination: {exc}", critical=True)
            return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--enabled", action="store_true")
    mode.add_argument("--check-build-deps", action="store_true")
    mode.add_argument("--deliver", action="store_true")
    mode.add_argument("--exec", dest="command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.enabled:
        return 0 if enabled() else 1
    if args.check_build_deps:
        try:
            build_tools()
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0
    if args.deliver:
        return deliver_picker()
    if not args.command:
        parser.error("--exec needs a program")
    os.execvpe(args.command[0], args.command, launch_environment())


if __name__ == "__main__":
    raise SystemExit(main())
