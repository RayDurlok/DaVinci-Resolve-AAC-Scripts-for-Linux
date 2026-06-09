#!/usr/bin/env python3
"""Auto-Abfang fuer Resolves Deliver-"File Destination"-Dialog.

Wartet darauf, dass Resolves nicht-nativer "File Destination"-Browser aufgeht,
schliesst ihn (Escape via ydotool) und ersetzt ihn durch einen nativen KDE-Picker,
dessen Auswahl per Scripting-API ins Location-Feld geschrieben wird.

Gates (beide muessen erfuellt sein, sonst bleibt Resolves Dialog unangetastet):
  * aktuelle Seite == "deliver"
  * der MediaPool-Watcher laeuft   (--require-mediapool-watcher, vom Tray gesetzt)

Aufruf:  python3 resolve_render_location_watch.py [--quiet] [--interval 0.3]
                                                 [--require-mediapool-watcher]
"""
import argparse
import fcntl
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import set_render_location as srl  # noqa: E402  (gleicher Ordner)

WINDOW_TITLE = "File Destination"
YDOTOOL_SOCKET = os.environ.get("YDOTOOL_SOCKET", "/tmp/ydotool_socket")
STOP_PATH = Path("/tmp/resolve_render_location_watch.stop")
LOCK_PATH = "/tmp/resolve_render_location_watch.lock"
KEY_ESC = "1"  # evdev KEY_ESC


def _acquire_singleton_lock():
    """Ensure only one watcher runs. Returns the held fd, or None if another instance owns it.
    The fd is kept open for the process lifetime (closing/exiting releases the lock)."""
    fd = open(LOCK_PATH, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fd.close()
        return None
    return fd

_running = True


def log(quiet, *parts):
    if not quiet:
        print("[render-location-watch]", *parts, flush=True)


def _xprop(args):
    return subprocess.run(["xprop", *args], capture_output=True, text=True).stdout


def find_file_destination_window():
    """Gibt die Fenster-ID des Resolve-'File Destination'-Dialogs zurueck, sonst None."""
    ids = re.findall(r"0x[0-9a-f]+", _xprop(["-root", "_NET_CLIENT_LIST"]))
    for wid in ids:
        wm_class = _xprop(["-id", wid, "WM_CLASS"])
        if "resolve" not in wm_class.lower():
            continue
        name = _xprop(["-id", wid, "_NET_WM_NAME"])
        m = re.search(r'"(.*)"', name)
        if m and m.group(1).strip() == WINDOW_TITLE:
            return wid
    return None


def mediapool_watcher_running():
    r = subprocess.run(
        ["pgrep", "-u", str(os.getuid()), "-f", "resolve_aac_mediapool_watch.py"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    return r.returncode == 0


def send_escape():
    env = dict(os.environ, YDOTOOL_SOCKET=YDOTOOL_SOCKET)
    subprocess.run(["ydotool", "key", f"{KEY_ESC}:1", f"{KEY_ESC}:0"], env=env, check=False)


def handle_intercept(resolve, quiet):
    # Das Fenster mit Titel "File Destination" existiert nur auf der Deliver-Page,
    # daher kein API-Page-Check noetig (waehrend des modalen Dialogs blockiert die API ohnehin).
    # Resolves Dialog zuverlaessig schliessen: beim ERSTEN Oeffnen hat es u. U. noch keinen
    # Fokus, ein einzelnes Esc verpufft. Daher Esc wiederholen, bis das Fenster weg ist.
    closed = False
    for _ in range(12):
        time.sleep(0.12)
        if find_file_destination_window() is None:
            closed = True
            break
        send_escape()
    if not closed:
        log(quiet, "warning: Resolve's File Destination dialog still open after Esc retries.")

    start = srl.load_start_dir(None)
    chosen = srl.pick_save_path(start)
    if not chosen:
        log(quiet, "Picker cancelled.")
        return resolve

    # Fresh handle for every intercept: a reused scripting connection goes stale after
    # UI actions, which made SetRenderSettings (esp. CustomName) silently not apply.
    resolve = srl.get_resolve()
    project = resolve.GetProjectManager().GetCurrentProject() if resolve else None
    if not project:
        srl.notify("Cannot reach the active Resolve project.", critical=True)
        return resolve
    target_dir, name = srl.apply_render_path(project, chosen)
    srl.notify(f"Location: {target_dir}" + (f"\nName: {name}" if name else ""))
    log(quiet, "set -> TargetDir:", target_dir, "| CustomName:", name or "(unchanged)")
    return resolve


def _stop(*_):
    global _running
    _running = False


def main():
    parser = argparse.ArgumentParser(description="Auto-Abfang fuer Resolves File-Destination-Dialog")
    parser.add_argument("--interval", type=float, default=0.3, help="Poll-Intervall in Sekunden")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--require-mediapool-watcher", action="store_true",
                        help="Nur abfangen, wenn der MediaPool-Watcher laeuft")
    args = parser.parse_args()

    lock_fd = _acquire_singleton_lock()  # noqa: F841 (held for process lifetime)
    if lock_fd is None:
        log(args.quiet, "another instance already runs, exiting.")
        return 0

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        STOP_PATH.unlink()
    except OSError:
        pass

    resolve = srl.get_resolve()
    handled_id = None
    log(args.quiet, "started.")

    while _running:
        if STOP_PATH.exists():
            log(args.quiet, "Stop file seen, exiting.")
            break

        wid = find_file_destination_window()
        if wid and wid != handled_id:
            handled_id = wid  # nur einmal pro geoeffnetem Fenster reagieren
            if args.require_mediapool_watcher and not mediapool_watcher_running():
                log(args.quiet, "MediaPool watcher off -> not intercepted.")
            else:
                log(args.quiet, "File Destination window detected -> intercepting.")
                resolve = handle_intercept(resolve, args.quiet)
        elif not wid:
            handled_id = None

        time.sleep(args.interval)

    log(args.quiet, "stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
