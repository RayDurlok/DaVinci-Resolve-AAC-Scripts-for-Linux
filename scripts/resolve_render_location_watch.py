#!/usr/bin/env python3
"""Auto-Abfang fuer Resolves nicht-nativen Deliver-Zieldialog.

Ersetzt den Deliver-"File Destination"-Browser durch einen nativen Save-Dialog.
MediaPool-Relink-Dialoge bleiben bei Resolve: Die Scripting-API zeigt keine
ausgewaehlten Bins und kann Einzel-/Mehrfach-Bin-Aktionen nicht sicher trennen.

Gate:
  * der MediaPool-Watcher laeuft   (--require-mediapool-watcher, vom Tray gesetzt)

Aufruf:  python3 resolve_render_location_watch.py [--quiet] [--interval 0.3]
                                                 [--require-mediapool-watcher]
"""
import argparse
import fcntl
import os
import re
import signal
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import set_render_location as srl  # noqa: E402  (gleicher Ordner)

FILE_DESTINATION_TITLE = "File Destination"
INTERCEPT_TITLES = {FILE_DESTINATION_TITLE}
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
    try:
        return subprocess.run(
            ["xprop", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        ).stdout
    except OSError:
        return ""


def find_intercept_window(titles):
    """Return (window-id, title) for a Resolve dialog whose title is in `titles`,
    else (None, None)."""
    ids = re.findall(r"0x[0-9a-f]+", _xprop(["-root", "_NET_CLIENT_LIST"]))
    for wid in ids:
        wm_class = _xprop(["-id", wid, "WM_CLASS"])
        if "resolve" not in wm_class.lower():
            continue
        name = _xprop(["-id", wid, "_NET_WM_NAME"])
        m = re.search(r'"(.*)"', name)
        title = m.group(1).strip() if m else ""
        if title in titles:
            return wid, title
    return None, None


def mediapool_watcher_running():
    r = subprocess.run(
        ["pgrep", "-u", str(os.getuid()), "-f", "resolve_aac_mediapool_watch.py"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    return r.returncode == 0


def send_escape():
    if not shutil.which("ydotool"):
        return False
    env = dict(os.environ, YDOTOOL_SOCKET=YDOTOOL_SOCKET)
    try:
        subprocess.run(
            ["ydotool", "key", f"{KEY_ESC}:1", f"{KEY_ESC}:0"],
            env=env,
            check=False,
        )
    except OSError:
        return False
    return True


def close_window_via_ewmh(wid):
    """Ask KWin to close one exact X11/XWayland window."""
    try:
        from Xlib import X, display
        from Xlib.protocol import event
    except Exception:
        return False
    disp = None
    try:
        disp = display.Display()
        root = disp.screen().root
        window = disp.create_resource_object("window", int(wid, 16))
        close_atom = disp.intern_atom("_NET_CLOSE_WINDOW")
        client_message = event.ClientMessage(
            window=window,
            client_type=close_atom,
            data=(32, [X.CurrentTime, 2, 0, 0, 0]),
        )
        root.send_event(
            client_message,
            event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask,
        )
        disp.flush()
        disp.sync()
        return True
    except Exception:
        return False
    finally:
        if disp is not None:
            try:
                disp.close()
            except Exception:
                pass


def activate_window_via_x(wid):
    """Activate a Resolve dialog before the final Escape-key fallback."""
    try:
        from Xlib import X, display
        from Xlib.protocol import event
    except Exception:
        return False
    disp = None
    try:
        disp = display.Display()
        root = disp.screen().root
        window = disp.create_resource_object("window", int(wid, 16))
        active_atom = disp.intern_atom("_NET_ACTIVE_WINDOW")
        client_message = event.ClientMessage(
            window=window,
            client_type=active_atom,
            data=(32, [2, X.CurrentTime, 0, 0, 0]),
        )
        root.send_event(
            client_message,
            event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask,
        )
        disp.flush()
        disp.sync()
        return True
    except Exception:
        return False
    finally:
        if disp is not None:
            try:
                disp.close()
            except Exception:
                pass


def close_window_via_x(wid):
    """Close window `wid` (hex string) by sending it WM_DELETE_WINDOW directly.

    This is exactly what a window manager delivers when you click a window's
    close button, and Qt/Tk honour it. Focus-independent: it targets the specific
    window regardless of which window currently has keyboard focus, unlike sending
    Escape through ydotool. Returns True if the request was sent, False if Xlib is
    unavailable or the send failed (caller then falls back to Escape).
    """
    try:
        from Xlib import X, display
        from Xlib.protocol import event
    except Exception:
        return False
    disp = None
    try:
        disp = display.Display()
        window = disp.create_resource_object("window", int(wid, 16))
        wm_protocols = disp.intern_atom("WM_PROTOCOLS")
        wm_delete_window = disp.intern_atom("WM_DELETE_WINDOW")
        client_message = event.ClientMessage(
            window=window,
            client_type=wm_protocols,
            data=(32, [wm_delete_window, X.CurrentTime, 0, 0, 0]),
        )
        window.send_event(client_message)
        disp.flush()
        disp.sync()
        return True
    except Exception:
        return False
    finally:
        if disp is not None:
            try:
                disp.close()
            except Exception:
                pass


def close_resolve_dialog(title, quiet):
    # Das Fenster mit Titel "File Destination" existiert nur auf der Deliver-Page,
    # daher kein API-Page-Check noetig (waehrend des modalen Dialogs blockiert die API ohnehin).
    # Ask KWin first, then send WM_DELETE_WINDOW directly. Global Escape is only
    # a last resort because focus may already have moved to another application.
    closed = False
    for attempt in range(20):
        wid, current_title = find_intercept_window({title})
        if current_title != title:
            wid = None
        if wid is None:
            closed = True
            break

        requested = close_window_via_ewmh(wid)
        if attempt >= 2 or not requested:
            requested = close_window_via_x(wid) or requested
        if attempt >= 5:
            activate_window_via_x(wid)
            time.sleep(0.05)
        if attempt >= 5 or not requested:
            send_escape()
        time.sleep(0.1)

    if not closed:
        log(quiet, f"warning: Resolve's {title!r} dialog still open after close attempts.")
    return closed


def wait_for_dialog_to_disappear(title):
    while _running and not STOP_PATH.exists():
        wid, current_title = find_intercept_window({title})
        if wid is None or current_title != title:
            return
        time.sleep(0.1)


def handle_file_destination_intercept(resolve, quiet):
    if not close_resolve_dialog(FILE_DESTINATION_TITLE, quiet):
        log(quiet, "Native picker skipped; keeping Resolve's File Destination dialog.")
        wait_for_dialog_to_disappear(FILE_DESTINATION_TITLE)
        return resolve

    # Let KWin finish focus/modal bookkeeping before opening the portal picker.
    time.sleep(0.15)

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


def handle_intercept(resolve, wid, title, quiet):
    if title == FILE_DESTINATION_TITLE:
        return handle_file_destination_intercept(resolve, quiet)
    return resolve


def _stop(*_):
    global _running
    _running = False


def main():
    parser = argparse.ArgumentParser(description="Auto-Abfang fuer Resolves Datei-/Ordnerdialoge")
    parser.add_argument("--interval", type=float, default=0.3, help="Poll-Intervall in Sekunden")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--require-mediapool-watcher", action="store_true",
                        help=argparse.SUPPRESS)  # accepted for compatibility with older tray versions
    args = parser.parse_args()

    lock_fd = _acquire_singleton_lock()  # noqa: F841 (held for process lifetime)
    if lock_fd is None:
        log(args.quiet, "another instance already runs, exiting.")
        return 0
    if not shutil.which("xprop"):
        log(args.quiet, "error: xprop is required to detect Resolve's File Destination window.")
        return 2

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

        wid, title = find_intercept_window(INTERCEPT_TITLES)
        if wid and wid != handled_id:
            handled_id = wid  # nur einmal pro geoeffnetem Fenster reagieren
            log(args.quiet, f"{title} window detected -> intercepting.")
            try:
                resolve = handle_intercept(resolve, wid, title, args.quiet)
                # Qt may reuse the same X11 window id for the next Browse
                # click. The handled dialog is gone (or the fallback wait
                # returned after it disappeared), so allow that id again.
                handled_id = None
            except Exception as exc:
                log(args.quiet, f"intercept failed: {exc}")
                log(args.quiet, traceback.format_exc())
        elif not wid:
            handled_id = None

        time.sleep(args.interval)

    log(args.quiet, "stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
