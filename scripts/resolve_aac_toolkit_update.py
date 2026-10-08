#!/usr/bin/env python3
"""Update the installed toolkit, without modifying Resolve or its AAC patch."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
from pathlib import Path, PurePosixPath

from resolve_aac_config import APP_VERSION, CONFIG_DIR
from resolve_aac_native import operation_lock, require_closed
from resolve_aac_update import wait_for_changes


PACKAGE = "davinci-resolve-toolkit"
REPOSITORY = "RayDurlok/DaVinci-Resolve-AAC-Scripts-for-Linux"
ASSET = "resolve-aac-tools-linux.tar.gz"
STOP_REQUEST = CONFIG_DIR / "toolkit_update_stop.request"
MAX_ARCHIVE_SIZE = 200 * 1024 * 1024
_UPDATE_CHECK_CACHE = {}
_UPDATE_CHECK_LOCK = threading.Lock()


def installation_kind(directory):
    directory = directory.resolve()
    if any((parent / marker).exists() for parent in (directory, directory.parent)
           for marker in (".git", ".git-local")):
        raise RuntimeError("This is a source checkout. Update it through Git; automatic installation is disabled here.")
    if shutil.which("rpm"):
        result = subprocess.run(
            ["rpm", "-qf", "--qf", "%{NAME}", str(directory / "resolve_aac_tray.py")],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip() == PACKAGE:
            return "rpm"
    if (directory / "install_user_tools.sh").is_file() and directory.stat().st_uid == os.getuid():
        return "archive"
    raise RuntimeError("Unknown installation type. Please use the update commands in the README.")


def version_tuple(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise RuntimeError(f"Unsupported release version: {value}")
    return tuple(int(part) for part in match.groups())


def latest_release():
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Resolve-Toolkit-Updater"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.loads(response.read(2 * 1024 * 1024))
    if release.get("draft") or release.get("prerelease"):
        raise RuntimeError("The latest release is not a stable release.")
    version = release["tag_name"]
    version_tuple(version)
    for asset in release.get("assets", []):
        if asset.get("name") == ASSET:
            expected = f"https://github.com/{REPOSITORY}/releases/download/{version}/{ASSET}"
            if asset.get("browser_download_url") != expected:
                raise RuntimeError("Unexpected release download URL.")
            digest = asset.get("digest", "") or ""
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise RuntimeError("The release has no SHA-256 digest. Please use the manual update instructions.")
            return version, expected, digest.split(":", 1)[1]
    raise RuntimeError("The latest release does not contain the Linux toolkit archive.")


def update_available(directory):
    kind = installation_kind(directory)
    if kind == "rpm":
        if not shutil.which("dnf"):
            return False
        result = subprocess.run(
            ["dnf", "--quiet", "--refresh", "check-update", PACKAGE],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
        )
        return result.returncode == 100
    version, _, _ = latest_release()
    return version_tuple(version) > version_tuple(APP_VERSION)


def cached_update_available(directory):
    key = (str(directory.resolve()), APP_VERSION)
    # Both the tray menu and settings ask; share one short-lived result.
    with _UPDATE_CHECK_LOCK:
        cached = _UPDATE_CHECK_CACHE.get(key)
        if cached is not None and time.monotonic() - cached[0] < 900:
            return cached[1]
        try:
            available = update_available(directory)
        except Exception:
            available = False
        _UPDATE_CHECK_CACHE[key] = (time.monotonic(), available)
        return available


def check_update_async(directory, report):
    def check():
        available = cached_update_available(directory)
        try:
            report(available)
        except RuntimeError:
            pass  # The settings window may have closed during the network request.
    threading.Thread(target=check, daemon=True).start()


def download_archive(url, checksum, destination):
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(url, timeout=60) as response, destination.open("wb") as target:
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_ARCHIVE_SIZE:
                raise RuntimeError("The release archive exceeds the download size limit.")
            target.write(chunk)
            digest.update(chunk)
    if digest.hexdigest() != checksum:
        raise RuntimeError("Release checksum mismatch. Nothing was installed.")


def extract_archive(archive, destination):
    # Only regular files/directories are needed; reject links and escaping paths.
    with tarfile.open(archive) as source:
        members = source.getmembers()
        if len(members) > 10000 or sum(member.size for member in members) > MAX_ARCHIVE_SIZE * 4:
            raise RuntimeError("The extracted release exceeds the size limit.")
        seen = set()
        for member in members:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or ".." in path.parts or not path.parts
                    or path.parts[0] != "resolve-aac-tools"
                    or not (member.isfile() or member.isdir()) or path in seen):
                raise RuntimeError("Unsafe or unexpected path in the release archive.")
            seen.add(path)
        for member in members:
            target = destination / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as data, target.open("xb") as output:
                    shutil.copyfileobj(data, output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
    app = destination / "resolve-aac-tools"
    for name in ("install_user_tools.sh", "resolve_aac_tray.py", "resolve_aac_config.py"):
        if not (app / name).is_file():
            raise RuntimeError(f"Incomplete release archive: missing {name}")
    return app


def process_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def require_idle(proc=Path("/proc")):
    processes = {}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            args = entry.joinpath("cmdline").read_bytes().decode(errors="replace").split("\0")
            fields = entry.joinpath("stat").read_text().rsplit(")", 1)[1].split()
            processes[int(entry.name)] = (int(fields[1]), args)
        except (OSError, ValueError, IndexError):
            continue
    for pid, (_, args) in processes.items():
        if not args or Path(args[0]).name != "ffmpeg":
            continue
        visited = set()
        while pid in processes and pid not in visited:
            visited.add(pid)
            pid, args = processes[pid]
            if any(Path(arg).name.startswith("resolve_aac_") and arg.endswith(".py") for arg in args):
                raise RuntimeError("A toolkit conversion is still running. Wait for it to finish before updating.")


def stop_tray(pid):
    if not process_alive(pid):
        return
    STOP_REQUEST.parent.mkdir(parents=True, exist_ok=True)
    STOP_REQUEST.write_text(str(pid))
    try:
        deadline = time.monotonic() + 30
        while process_alive(pid):
            if time.monotonic() >= deadline:
                raise RuntimeError("The toolkit did not close. No update was installed. Close it and try again.")
            time.sleep(0.2)
    finally:
        STOP_REQUEST.unlink(missing_ok=True)


def restart_tray(directory):
    log = CONFIG_DIR / "toolkit-update-restart.log"
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with log.open("a") as output:
        subprocess.Popen(
            [sys.executable, str(directory / "resolve_aac_tray.py"), "--settings"],
            stdin=subprocess.DEVNULL, stdout=output, stderr=output, start_new_session=True,
        )


def refresh_menu_links(previous, current, menu=None):
    if menu is None:
        menu = Path.home() / ".local/share/DaVinciResolve/Fusion/Scripts/Edit/DaVinci Resolve Toolkit"
    if not menu.is_dir():
        return
    for link in menu.glob("*.py"):
        if not link.is_symlink():
            continue
        target = link.resolve()
        replacement = current / target.name
        if target.parent == previous.resolve() and replacement.is_file():
            with tempfile.TemporaryDirectory(prefix=".update-", dir=menu) as temporary:
                staged = Path(temporary) / "link"
                staged.symlink_to(replacement)
                staged.replace(link)


def perform_update(directory, tray_pid):
    kind = installation_kind(directory)
    require_closed()
    require_idle()
    if kind == "rpm" and not (shutil.which("dnf") and shutil.which("sudo")):
        raise RuntimeError("This RPM installation needs dnf and sudo to update.")
    restart_directory = directory
    stopped = False
    try:
        # Serializes toolkit, native-patch and Resolve updates, including approval waits.
        with operation_lock(), tempfile.TemporaryDirectory(prefix="resolve-toolkit-download-") as temporary:
            app = None
            if kind == "archive":
                print("Checking the latest GitHub release...", flush=True)
                version, url, checksum = latest_release()
                if version_tuple(version) <= version_tuple(APP_VERSION):
                    print(f"Toolkit {APP_VERSION} is already up to date.")
                    return
                print(f"Downloading and verifying {version}...", flush=True)
                archive = Path(temporary) / ASSET
                download_archive(url, checksum, archive)
                app = extract_archive(archive, Path(temporary) / "unpacked")
            print("\nUpdate Toolkit only. Settings, cache and the Resolve AAC patch are kept.")
            print("Close Resolve and wait for all remux/render jobs to finish. Keep Resolve closed until done.")
            if input("Install the update and restart the toolkit now? [y/N] ").strip().lower() not in ("y", "yes"):
                print("Update cancelled.")
                return
            require_closed()
            require_idle()
            stopped = True
            stop_tray(tray_pid)
            require_closed()
            if kind == "rpm":
                print("Checking enabled package repositories; approve DNF's update when prompted.", flush=True)
                with wait_for_changes():
                    subprocess.run(["sudo", "dnf", "--refresh", "upgrade", PACKAGE], check=True)
            else:
                # Installer launchers point at this folder, so it must outlive this process.
                data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
                releases = data / "resolve-aac-tools" / "releases"
                releases.mkdir(parents=True, exist_ok=True)
                retained = Path(tempfile.mkdtemp(prefix=f"{version}-", dir=releases)) / "resolve-aac-tools"
                shutil.copytree(app, retained)
                print(f"Installing from {retained}\nKeep this directory; it contains the installed application.", flush=True)
                with wait_for_changes():
                    subprocess.run(["bash", str(retained / "install_user_tools.sh")], cwd=retained, check=True,
                                   env={**os.environ, "RESOLVE_AAC_INSTALL_NO_START": "1"})
                    restart_directory = retained
                    refresh_menu_links(directory, retained)
            print("Update finished. Restarting the toolkit.", flush=True)
    finally:
        if stopped:
            restart_tray(restart_directory)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tray-pid", type=int, required=True)
    args = parser.parse_args(argv)
    if args.tray_pid <= 1:
        parser.error("invalid tray PID")
    result = 0
    try:
        perform_update(Path(__file__).resolve().parent, args.tray_pid)
    except (Exception, KeyboardInterrupt) as exc:
        print(f"\nToolkit update failed: {exc or 'cancelled'}.\nResolve and its AAC patch were not modified.", file=sys.stderr)
        result = 1
    try:
        input("\nPress Enter to close this window.")
    except (EOFError, KeyboardInterrupt):
        pass
    return result


if __name__ == "__main__":
    raise SystemExit(main())
