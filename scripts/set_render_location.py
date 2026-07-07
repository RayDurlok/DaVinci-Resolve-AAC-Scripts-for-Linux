#!/usr/bin/env python3
"""Render-Ziel ("Location") in DaVinci Resolve via nativem KDE-Ordnerdialog setzen.

Ersetzt den haesslichen, nicht-nativen Resolve-"Browse"-Button im Deliver-Tab:
oeffnet kdialog (Fallback zenity), schreibt die Auswahl per Scripting-API direkt
ins Location-Feld (project.SetRenderSettings({"TargetDir": ...})).

Aufruf:  python3 set_render_location.py [start_dir]
"""
import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

RESOLVE_SCRIPT_MODULE = "/opt/resolve/Developer/Scripting/Modules/DaVinciResolveScript.py"
STATE_FILE = Path.home() / ".cache" / "resolve-aac" / "last_render_location"


def get_resolve():
    os.environ.setdefault("RESOLVE_SCRIPT_API", "/opt/resolve/Developer/Scripting")
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", "/opt/resolve/libs/Fusion/fusionscript.so")
    module_dir = str(Path(RESOLVE_SCRIPT_MODULE).parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    module = importlib.import_module("DaVinciResolveScript")
    return module.scriptapp("Resolve")


# Title MUST contain a marker word ("save"/"file"/"open"/"folder") so InputPilot's
# file-dialog detector recognises it (it matches caption + resource_class against those
# markers). The word can be overridden via env, but keep a marker word in it.
DIALOG_TITLE = os.environ.get("RESOLVE_RENDER_DIALOG_TITLE", "Save to location")
FOLDER_DIALOG_TITLE = os.environ.get("RESOLVE_FOLDER_DIALOG_TITLE", "Select folder")


def _portal_save_file(title: str, start_dir: str) -> str | None:
    """Open the SaveFile dialog through xdg-desktop-portal (same window identity as
    Firefox/Resolve save dialogs: resource_class 'org.freedesktop.impl.portal.desktop.kde',
    modal) so InputPilot recognises and drives it.

    Returns the chosen path, or None on cancel. Raises if the portal is unavailable.
    """
    import gi
    gi.require_version("Gio", "2.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import Gio, GLib
    from urllib.parse import unquote, urlparse

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    token = "resolve_render_%d" % os.getpid()
    sender = bus.get_unique_name()[1:].replace(".", "_")
    handle_path = "/org/freedesktop/portal/desktop/request/%s/%s" % (sender, token)

    loop = GLib.MainLoop()
    result: dict = {}

    def on_response(_conn, _sender, _path, _iface, _signal, params):
        response, results = params.unpack()
        result["response"] = response
        result["uris"] = results.get("uris", [])
        loop.quit()

    sub_id = bus.signal_subscribe(
        "org.freedesktop.portal.Desktop", "org.freedesktop.portal.Request",
        "Response", handle_path, None, Gio.DBusSignalFlags.NONE, on_response,
    )
    options = {
        "handle_token": GLib.Variant("s", token),
        "current_folder": GLib.Variant("ay", (start_dir.rstrip("/") + "/").encode("utf-8") + b"\0"),
    }
    try:
        bus.call_sync(
            "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.FileChooser", "SaveFile",
            GLib.Variant("(ssa{sv})", ("", title, options)),
            GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, -1, None,
        )
        GLib.timeout_add_seconds(300, lambda: (loop.quit(), False)[1])
        loop.run()
    finally:
        bus.signal_unsubscribe(sub_id)

    if result.get("response") == 0 and result.get("uris"):
        parsed = urlparse(result["uris"][0])
        if parsed.scheme == "file":
            return unquote(parsed.path)
    return None


def _portal_select_folder(title: str, start_dir: str) -> str | None:
    """Open a native folder picker through xdg-desktop-portal."""
    import gi
    gi.require_version("Gio", "2.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import Gio, GLib
    from urllib.parse import unquote, urlparse

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    token = "resolve_folder_%d" % os.getpid()
    sender = bus.get_unique_name()[1:].replace(".", "_")
    handle_path = "/org/freedesktop/portal/desktop/request/%s/%s" % (sender, token)

    loop = GLib.MainLoop()
    result: dict = {}

    def on_response(_conn, _sender, _path, _iface, _signal, params):
        response, results = params.unpack()
        result["response"] = response
        result["uris"] = results.get("uris", [])
        loop.quit()

    sub_id = bus.signal_subscribe(
        "org.freedesktop.portal.Desktop", "org.freedesktop.portal.Request",
        "Response", handle_path, None, Gio.DBusSignalFlags.NONE, on_response,
    )
    options = {
        "handle_token": GLib.Variant("s", token),
        "directory": GLib.Variant("b", True),
        "current_folder": GLib.Variant("ay", (start_dir.rstrip("/") + "/").encode("utf-8") + b"\0"),
    }
    try:
        bus.call_sync(
            "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.FileChooser", "OpenFile",
            GLib.Variant("(ssa{sv})", ("", title, options)),
            GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, -1, None,
        )
        GLib.timeout_add_seconds(300, lambda: (loop.quit(), False)[1])
        loop.run()
    finally:
        bus.signal_unsubscribe(sub_id)

    if result.get("response") == 0 and result.get("uris"):
        parsed = urlparse(result["uris"][0])
        if parsed.scheme == "file":
            return unquote(parsed.path)
    return None


def pick_save_path(start_dir: str) -> str | None:
    """Classic 'Save As' dialog (location + name field, InputPilot-compatible).

    Prefers the xdg-desktop-portal dialog so the window matches what InputPilot expects;
    falls back to kdialog/zenity only if the portal is unavailable.
    Returns the full path (folder + name) or None on cancel.
    """
    try:
        return _portal_save_file(DIALOG_TITLE, start_dir)
    except Exception:
        pass  # Portal nicht verfuegbar -> Fallback

    start = start_dir.rstrip("/") + "/"
    if shutil.which("kdialog"):
        cmd = ["kdialog", "--title", DIALOG_TITLE, "--getsavefilename", start]
    elif shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", "--save", f"--title={DIALOG_TITLE}",
               f"--filename={start}"]
    else:
        notify("No file dialog found (portal/kdialog/zenity missing).", critical=True)
        return None
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    path = proc.stdout.strip()
    return path or None


def pick_folder_path(start_dir: str, title: str = FOLDER_DIALOG_TITLE) -> str | None:
    """Native folder picker used for Resolve relink/source-folder dialogs."""
    start = start_dir.rstrip("/") + "/"
    if shutil.which("kdialog"):
        cmd = ["kdialog", "--title", title, "--getexistingdirectory", start]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return None
        path = proc.stdout.strip()
        return path or None

    try:
        return _portal_select_folder(title, start_dir)
    except Exception:
        pass

    if shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", "--directory", f"--title={title}",
               f"--filename={start}"]
    else:
        notify("No folder dialog found (portal/kdialog/zenity missing).", critical=True)
        return None
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    path = proc.stdout.strip()
    return path or None


def apply_render_path(project, chosen: str) -> tuple[str, str]:
    """Schreibt Ordner -> Location (TargetDir) und Dateiname -> Custom Name in die
    Render-Settings. Gibt (target_dir, name) zurueck."""
    target_dir = os.path.dirname(chosen) or chosen
    name = os.path.splitext(os.path.basename(chosen))[0]
    settings = {"TargetDir": target_dir}
    if name:
        settings["CustomName"] = name
    project.SetRenderSettings(settings)
    save_start_dir(target_dir)
    return target_dir, name


def notify(message: str, critical: bool = False, title: str = "Render location"):
    if shutil.which("notify-send"):
        args = ["notify-send", "-a", "DaVinci Resolve"]
        if critical:
            args += ["-u", "critical"]
        subprocess.run(args + [title, message], check=False)
    print(message)


def load_start_dir(argv_start: str | None) -> str:
    if argv_start and os.path.isdir(argv_start):
        return argv_start
    try:
        last = STATE_FILE.read_text().strip()
        if last and os.path.isdir(last):
            return last
    except OSError:
        pass
    return str(Path.home())


def save_start_dir(path: str):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(path)
    except OSError:
        pass


def main() -> int:
    start = load_start_dir(sys.argv[1] if len(sys.argv) > 1 else None)
    chosen = pick_save_path(start)
    if not chosen:
        return 0  # Nutzer hat abgebrochen

    resolve = get_resolve()
    if not resolve:
        notify("Cannot connect to Resolve (is it running with scripting enabled?).", critical=True)
        return 1
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        notify("No active project in Resolve.", critical=True)
        return 1

    target_dir, name = apply_render_path(project, chosen)
    notify(f"Location: {target_dir}" + (f"\nName: {name}" if name else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
