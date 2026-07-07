#!/usr/bin/env python3
"""Auto-Abfang fuer Resolves nicht-native Datei-/Ordnerdialoge.

Ersetzt den Deliver-"File Destination"-Browser durch einen nativen Save-Dialog.
Der MediaPool-"Relink Clip / Select Source Folder"-Browser wird fuer einzelne
Clips und den aktuellen Bin per Resolve-API ersetzt. Mehrfach selektierte Bins
sind ueber die Resolve-Scripting-API nicht sichtbar; in dem Fall bleibt Resolves
eigener Dialog offen und Resolve uebernimmt das Relinking selbst.

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
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import set_render_location as srl  # noqa: E402  (gleicher Ordner)

FILE_DESTINATION_TITLE = "File Destination"
RELINK_SOURCE_FOLDER_TITLE = "Select Source Folder"
INTERCEPT_TITLES = {FILE_DESTINATION_TITLE, RELINK_SOURCE_FOLDER_TITLE}
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
    env = dict(os.environ, YDOTOOL_SOCKET=YDOTOOL_SOCKET)
    subprocess.run(["ydotool", "key", f"{KEY_ESC}:1", f"{KEY_ESC}:0"], env=env, check=False)


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
    # Resolves Dialog zuverlaessig schliessen: ydotool-Esc geht ans fokussierte Fenster und
    # verpufft beim ERSTEN Oeffnen (Dialog noch nicht fokussiert). Daher primaer ein gezieltes
    # EWMH _NET_CLOSE_WINDOW an genau dieses Fenster (fokus-unabhaengig); Esc nur als Fallback.
    closed = False
    for attempt in range(15):
        wid, current_title = find_intercept_window({title})
        if current_title != title:
            wid = None
        if wid is None:
            closed = True
            break
        if not close_window_via_x(wid):
            send_escape()            # Xlib unavailable -> focus-based fallback
        elif attempt >= 3:
            send_escape()            # EWMH close not taking effect -> add Esc fallback
        time.sleep(0.12)
    if not closed:
        log(quiet, f"warning: Resolve's {title!r} dialog still open after close attempts.")
    return closed


def handle_file_destination_intercept(resolve, quiet):
    close_resolve_dialog(FILE_DESTINATION_TITLE, quiet)

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


def _selected_clips(media_pool):
    selected = media_pool.GetSelectedClips() or []
    if isinstance(selected, dict):
        selected = list(selected.values())
    return [clip for clip in selected if clip]


def _folder_clips(folder):
    clips = []
    try:
        clips.extend(folder.GetClipList() or [])
    except Exception:
        pass
    try:
        subfolders = folder.GetSubFolderList() or []
    except Exception:
        subfolders = []
    for child in subfolders:
        clips.extend(_folder_clips(child))
    return [clip for clip in clips if clip]


def _choose_relink_scope(selected_clips, bin_clips):
    if not selected_clips:
        return "bin"
    if len(bin_clips) > len(selected_clips):
        return "bin"
    return "selection"


def _relink_candidates(media_pool):
    selected_clips = _selected_clips(media_pool)

    try:
        current_folder = media_pool.GetCurrentFolder()
    except Exception:
        current_folder = None

    bin_clips = _folder_clips(current_folder) if current_folder else []
    scope = _choose_relink_scope(selected_clips, bin_clips)
    if scope == "bin" and bin_clips:
        return bin_clips, "current bin"
    if selected_clips:
        return selected_clips, "selection"
    if bin_clips:
        return bin_clips, "current bin"

    return [], "none"


def _clip_source_folder(clip):
    try:
        props = clip.GetClipProperty() or {}
    except Exception:
        return None
    for key in ("File Path", "File Name"):
        value = props.get(key)
        if value:
            path = Path(str(value)).expanduser()
            if path.is_dir():
                return str(path)
            if path.parent.exists():
                return str(path.parent)
    return None


def _clip_expected_name(clip):
    try:
        props = clip.GetClipProperty() or {}
    except Exception:
        return None

    for key in ("File Path", "File Name"):
        value = props.get(key)
        if value:
            name = Path(str(value)).name
            if name:
                return name
    return None


def _group_clips_by_relink_folder(clips, chosen_folder):
    chosen = Path(chosen_folder).expanduser()
    grouped = {}
    missing = []
    skipped = 0

    for clip in clips:
        expected_name = _clip_expected_name(clip)
        if not expected_name:
            skipped += 1
            continue

        direct = chosen / expected_name
        if direct.exists():
            grouped.setdefault(str(chosen), []).append(clip)
            continue

        matches = []
        try:
            matches = [path for path in chosen.rglob(expected_name) if path.is_file()]
        except OSError:
            matches = []

        if matches:
            grouped.setdefault(str(matches[0].parent), []).append(clip)
        else:
            missing.append(expected_name)

    return grouped, missing, skipped


def handle_relink_intercept(resolve, quiet):
    # Query the media pool BEFORE closing Resolve's dialog. Resolve exposes selected
    # clips and the current bin, but NOT multiple selected bins. If we cannot
    # enumerate anything to relink (e.g. several selected bins), we must leave
    # Resolve's own dialog open and let Resolve handle it -- closing it first (as
    # before) just made the dialog vanish without relinking anything.
    resolve = srl.get_resolve()
    project = resolve.GetProjectManager().GetCurrentProject() if resolve else None
    media_pool = project.GetMediaPool() if project else None
    if not media_pool:
        log(quiet, "MediaPool unreachable -> leaving Resolve's relink dialog open.")
        return resolve

    clips, clip_source = _relink_candidates(media_pool)
    log(quiet, f"relink probe (pre-close): {len(clips)} clip(s) from {clip_source}")
    if not clips:
        log(quiet, "No relinkable clips via API (e.g. multiple bins) -> leaving Resolve's relink dialog open.")
        return resolve

    # We can relink these -> replace Resolve's non-native dialog with the native picker.
    close_resolve_dialog(RELINK_SOURCE_FOLDER_TITLE, quiet)

    start = _clip_source_folder(clips[0]) or srl.load_start_dir(None)
    chosen = srl.pick_folder_path(start, "Select source folder")
    if not chosen:
        log(quiet, "Relink picker cancelled.")
        return resolve

    grouped, missing, skipped = _group_clips_by_relink_folder(clips, chosen)
    relinked = 0
    failed = 0
    for folder, folder_clips in grouped.items():
        if media_pool.RelinkClips(folder_clips, folder):
            relinked += len(folder_clips)
            log(quiet, f"relinked {len(folder_clips)} clip(s) -> {folder}")
        else:
            failed += len(folder_clips)
            log(quiet, f"relink failed for {len(folder_clips)} clip(s) -> {folder}")

    if relinked and not failed and not missing:
        srl.save_start_dir(chosen)
        srl.notify(f"Relinked {relinked} clip(s)\nFolder: {chosen}", title="Relink clips")
    elif relinked:
        srl.save_start_dir(chosen)
        details = [f"Folder: {chosen}", f"Relinked: {relinked}"]
        if failed:
            details.append(f"API failed: {failed}")
        if missing:
            preview = ", ".join(missing[:3])
            suffix = "..." if len(missing) > 3 else ""
            details.append(f"Missing: {preview}{suffix}")
        if skipped:
            details.append(f"Skipped non-file items: {skipped}")
        srl.notify("Relink partially done.\n" + "\n".join(details), title="Relink clips")
    else:
        details = [f"Folder: {chosen}"]
        if failed:
            details.append(f"API failed: {failed}")
        if missing:
            preview = ", ".join(missing[:3])
            suffix = "..." if len(missing) > 3 else ""
            details.append(f"Missing: {preview}{suffix}")
        if skipped:
            details.append(f"Skipped non-file items: {skipped}")
        srl.notify("Relink failed.\n" + "\n".join(details), critical=True, title="Relink clips")
    return resolve


def handle_intercept(resolve, wid, title, quiet):
    if title == FILE_DESTINATION_TITLE:
        return handle_file_destination_intercept(resolve, quiet)
    if title == RELINK_SOURCE_FOLDER_TITLE:
        return handle_relink_intercept(resolve, quiet)
    return resolve


def _stop(*_):
    global _running
    _running = False


def main():
    parser = argparse.ArgumentParser(description="Auto-Abfang fuer Resolves Datei-/Ordnerdialoge")
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

        wid, title = find_intercept_window(INTERCEPT_TITLES)
        if wid and wid != handled_id:
            handled_id = wid  # nur einmal pro geoeffnetem Fenster reagieren
            if args.require_mediapool_watcher and not mediapool_watcher_running():
                log(args.quiet, "MediaPool watcher off -> not intercepted.")
            else:
                log(args.quiet, f"{title} window detected -> intercepting.")
                resolve = handle_intercept(resolve, wid, title, args.quiet)
        elif not wid:
            handled_id = None

        time.sleep(args.interval)

    log(args.quiet, "stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
