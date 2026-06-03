#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

try:
    from PySide6.QtCore import QObject, QTimer, QUrl
    from PySide6.QtGui import QAction, QDesktopServices, QIcon
    from PySide6.QtWidgets import (
        QApplication,
        QFileDialog,
        QMenu,
        QMessageBox,
        QStyle,
        QSystemTrayIcon,
    )
except ImportError:
    print("Resolve AAC Tray requires PySide6.", file=sys.stderr)
    print("Install it with your distro package manager, for example:", file=sys.stderr)
    print("  Fedora: sudo dnf install python3-pyside6", file=sys.stderr)
    print("  Arch:   sudo pacman -S pyside6", file=sys.stderr)
    print("  Debian/Ubuntu package names vary; search for PySide6/Qt6 bindings.", file=sys.stderr)
    raise SystemExit(2)


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = Path.home() / ".config" / "resolve-aac-tools"
CONFIG_PATH = CONFIG_DIR / "config.json"
START_REQUEST_PATH = CONFIG_DIR / "start_resolve.request"
AUTOSTART_DIR = Path.home() / ".config" / "autostart"
AUTOSTART_PATH = AUTOSTART_DIR / "resolve-aac-tray.desktop"
INSTALLED_TRAY_COMMAND = Path.home() / ".local" / "bin" / "resolve-aac-tray"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "resolve-aac-remux"
LOG_PATH = Path("/tmp/resolve_aac_launcher.log")
STOP_PATH = Path("/tmp/resolve_aac_mediapool_watch.stop")
EXPORT_WATCH_LOG_PATH = Path("/tmp/resolve_aac_export_watch.log")
EXPORT_WATCH_STOP_PATH = Path("/tmp/resolve_aac_export_watch.stop")
RESOLVE_FONT_WRAPPER_PATH = Path.home() / ".local" / "bin" / "resolve-with-fonts"
RESOLVE_DESKTOP_OVERRIDE_PATH = (
    Path.home() / ".local" / "share" / "applications" / "com.blackmagicdesign.resolve.desktop"
)
FUSION_PREFS_PATH = Path.home() / ".local" / "share" / "DaVinciResolve" / "Fusion" / "Profiles" / "Default" / "Fusion.prefs"
MANUAL_RESOLVE_CHECK_MS = 10000
EXPORT_PLUGIN_VERSION = "v1.0.1"
EXPORT_PLUGIN_URL = (
    "https://github.com/Toxblh/davinci-linux-aac-codec/releases/download/"
    f"{EXPORT_PLUGIN_VERSION}/aac_encoder_plugin-linux-bundle.tar.gz"
)
EXPORT_PLUGIN_SHA256 = "fc0ef6af76f33b3d2a8d4b03385837e8f014a35dbd2afb311a82c5d57c59136f"
EXPORT_PLUGIN_BUNDLE = "aac_encoder_plugin.dvcp.bundle"
EXPORT_PLUGIN_FILE = "aac_encoder_plugin.dvcp"
EXPORT_PLUGIN_TARGET_DIR = (
    Path("/opt/resolve/IOPlugins")
    / EXPORT_PLUGIN_BUNDLE
    / "Contents"
    / "Linux-x86-64"
)
EXPORT_PLUGIN_TARGET_FILE = EXPORT_PLUGIN_TARGET_DIR / EXPORT_PLUGIN_FILE


def load_config():
    defaults = {
        "use_cache": False,
        "cache_dir": str(DEFAULT_CACHE_DIR),
        "watch_manual_resolve": True,
        "remux_exports": False,
    }
    try:
        data = json.loads(CONFIG_PATH.read_text())
    except Exception:
        return defaults

    defaults.update({key: data[key] for key in defaults if key in data})
    if "remux_exports" not in data and "web_export_watch" in data:
        defaults["remux_exports"] = bool(data["web_export_watch"])
    return defaults


def save_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")


def tray_command():
    if INSTALLED_TRAY_COMMAND.exists():
        return INSTALLED_TRAY_COMMAND
    return Path(sys.argv[0]).resolve()


def autostart_enabled():
    return AUTOSTART_PATH.exists()


def write_autostart_file():
    AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
    AUTOSTART_PATH.write_text(
        "\n".join([
            "[Desktop Entry]",
            "Type=Application",
            "Name=Resolve AAC Tools",
            "Comment=Start Resolve AAC tray at login",
            f"Exec={tray_command()}",
            "Terminal=false",
            "X-GNOME-Autostart-enabled=true",
            "",
        ])
    )


def remove_autostart_file():
    try:
        AUTOSTART_PATH.unlink()
    except FileNotFoundError:
        pass


def parse_args():
    parser = argparse.ArgumentParser(description="Resolve AAC system tray helper")
    parser.add_argument(
        "--start-resolve",
        action="store_true",
        help="start Resolve with the MediaPool watcher after opening the tray",
    )
    return parser.parse_args()


class ResolveAacTray(QObject):
    def __init__(self, start_resolve=False):
        self.app = QApplication(sys.argv)
        super().__init__()
        self.app.setQuitOnLastWindowClosed(False)
        self.config = load_config()
        self.process = None
        self.watcher_process = None
        self.export_watcher_process = None
        self.export_watcher_log_file = None
        self.manual_resolve_was_running = False

        icon = QIcon.fromTheme("media-playback-start")
        if icon.isNull():
            icon = self.app.style().standardIcon(QStyle.SP_MediaPlay)

        self.tray = QSystemTrayIcon(icon)
        self.tray.setToolTip("Resolve AAC Tools")
        self.menu = QMenu()
        if hasattr(self.menu, "setToolTipsVisible"):
            self.menu.setToolTipsVisible(True)

        self.status_action = QAction("Stopped")
        self.status_action.setEnabled(False)
        self.status_action.setToolTip("Current launcher state and selected output mode.")
        self.menu.addAction(self.status_action)
        self.menu.addSeparator()

        self.start_action = QAction("Start Resolve + MediaPool Watcher")
        self.start_action.setToolTip("Launch DaVinci Resolve and start automatic AAC remux replacement.")
        self.start_action.triggered.connect(self.start_resolve)
        self.menu.addAction(self.start_action)

        self.stop_action = QAction("Stop Watcher")
        self.stop_action.setToolTip("Stop the MediaPool watcher while keeping the tray available.")
        self.stop_action.triggered.connect(self.stop_watcher)
        self.menu.addAction(self.stop_action)

        self.menu.addSeparator()

        self.cache_action = QAction("Use cache folder")
        self.cache_action.setCheckable(True)
        self.cache_action.setChecked(bool(self.config["use_cache"]))
        self.cache_action.setToolTip("Store remuxed MOV/PCM files in the selected cache folder.")
        self.cache_action.toggled.connect(self.set_use_cache)
        self.menu.addAction(self.cache_action)

        self.autostart_action = QAction("Start tray at login")
        self.autostart_action.setCheckable(True)
        self.autostart_action.setChecked(autostart_enabled())
        self.autostart_action.setToolTip("Open only the tray icon automatically after login.")
        self.autostart_action.toggled.connect(self.set_autostart)
        self.menu.addAction(self.autostart_action)

        self.watch_manual_action = QAction("Watch manual Resolve starts")
        self.watch_manual_action.setCheckable(True)
        self.watch_manual_action.setChecked(bool(self.config["watch_manual_resolve"]))
        self.watch_manual_action.setToolTip("Start the MediaPool watcher when Resolve is opened outside this tray.")
        self.watch_manual_action.toggled.connect(self.set_watch_manual_resolve)
        self.menu.addAction(self.watch_manual_action)

        self.remux_exports_action = QAction("Remux exports to webfriendly AAC")
        self.remux_exports_action.setCheckable(True)
        self.remux_exports_action.setChecked(bool(self.config["remux_exports"]))
        self.remux_exports_action.setToolTip(
            "Detect Resolve render outputs automatically and replace broken AAC metadata in-place."
        )
        self.remux_exports_action.toggled.connect(self.set_remux_exports)
        self.menu.addAction(self.remux_exports_action)

        self.export_plugin_action = QAction("Install AAC export plugin")
        self.export_plugin_action.setToolTip("Install once; status changes to installed when the export plugin is present.")
        self.export_plugin_action.triggered.connect(self.handle_export_plugin_action)
        self.menu.addAction(self.export_plugin_action)

        self.resolve_font_action = QAction("Resolve font fix: Install")
        self.resolve_font_action.setToolTip(
            "Make Resolve and Fusion scan user-installed font folders such as /usr/local/share/fonts."
        )
        self.resolve_font_action.triggered.connect(self.handle_resolve_font_action)
        self.menu.addAction(self.resolve_font_action)

        self.choose_cache_action = QAction("Choose cache folder...")
        self.choose_cache_action.setToolTip("Pick where cached remux files should be stored.")
        self.choose_cache_action.triggered.connect(self.choose_cache_folder)
        self.menu.addAction(self.choose_cache_action)

        self.open_cache_action = QAction("Open cache folder")
        self.open_cache_action.setToolTip("Open the currently selected cache folder in the file manager.")
        self.open_cache_action.triggered.connect(lambda: self.open_path(Path(self.config["cache_dir"])))
        self.menu.addAction(self.open_cache_action)

        self.open_log_action = QAction("Open launcher log")
        self.open_log_action.setToolTip("Open the Resolve AAC launcher log for troubleshooting.")
        self.open_log_action.triggered.connect(lambda: self.open_path(LOG_PATH))
        self.menu.addAction(self.open_log_action)

        self.menu.addSeparator()

        self.quit_action = QAction("Quit")
        self.quit_action.setToolTip("Close only the tray app.")
        self.quit_action.triggered.connect(self.quit)
        self.menu.addAction(self.quit_action)

        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.on_activated)
        self.tray.show()

        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)

        self.manual_resolve_timer = QTimer()
        self.manual_resolve_timer.timeout.connect(self.check_manual_resolve)
        self.manual_resolve_timer.start(MANUAL_RESOLVE_CHECK_MS)

        if self.config["remux_exports"]:
            QTimer.singleShot(500, lambda: self.start_export_watcher(notify=False))

        self.update_status()

        if start_resolve:
            QTimer.singleShot(250, self.start_resolve)

    def notify(self, title, message):
        self.tray.showMessage(title, message, QSystemTrayIcon.Information, 4000)

    def error(self, title, message):
        QMessageBox.warning(None, title, message)

    def launcher_path(self):
        return SCRIPT_DIR / "resolve-with-aac-mediapool-watch.sh"

    def stop_path(self):
        return SCRIPT_DIR / "resolve_aac_mediapool_watch_stop.py"

    def watcher_path(self):
        return SCRIPT_DIR / "resolve_aac_mediapool_watch.py"

    def export_watcher_path(self):
        return SCRIPT_DIR / "resolve_aac_export_watch.py"

    def fusion_font_paths(self):
        paths = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts")]
        local_fonts = Path.home() / ".local" / "share" / "fonts"
        if local_fonts.exists():
            paths.append(local_fonts)

        user_fonts = Path.home() / ".fonts"
        if user_fonts.exists():
            paths.append(user_fonts)

        local_system_fonts = Path("/usr/local/share/fonts")
        if local_system_fonts.exists():
            paths.extend(sorted(path for path in local_system_fonts.iterdir() if path.is_dir()))

        return [str(path) for path in paths if path.exists()]

    def fusion_font_path_string(self):
        return ";".join(self.fusion_font_paths())

    def current_env(self):
        env = os.environ.copy()
        if self.resolve_font_fix_installed():
            font_paths = [path for path in env.get("FUSION_FONTS", "").split(";") if path]
            for path in self.fusion_font_paths():
                if path not in font_paths:
                    font_paths.append(path)
            env["FUSION_FONTS"] = ";".join(font_paths)
            env["RESOLVE_FONT_FIX"] = "1"

        if self.config["use_cache"]:
            cache_dir = Path(self.config["cache_dir"]).expanduser()
            cache_dir.mkdir(parents=True, exist_ok=True)
            env["RESOLVE_AAC_CACHE_DIR"] = str(cache_dir)
        else:
            env.pop("RESOLVE_AAC_CACHE_DIR", None)
        return env

    def watcher_args(self):
        args = [
            sys.executable,
            str(self.watcher_path()),
            "--interval",
            os.environ.get("RESOLVE_AAC_WATCH_INTERVAL", "5"),
            "--quiet",
        ]
        if self.config["use_cache"]:
            cache_dir = Path(self.config["cache_dir"]).expanduser()
            cache_dir.mkdir(parents=True, exist_ok=True)
            args.extend(["--cache-dir", str(cache_dir)])
        return args

    def export_watcher_args(self):
        return [
            sys.executable,
            str(self.export_watcher_path()),
            "--detect-resolve-outputs",
            "--replace",
            "--no-backup",
            "--quiet",
        ]

    def resolve_is_running(self):
        try:
            result = subprocess.run(
                ["pgrep", "-u", str(os.getuid()), "-f", "/opt/resolve/bin/resolve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            return False
        return result.returncode == 0

    def watcher_is_running(self):
        if self.watcher_process and self.watcher_process.poll() is None:
            return True

        try:
            result = subprocess.run(
                ["pgrep", "-u", str(os.getuid()), "-f", "resolve_aac_mediapool_watch.py"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            return False
        return result.returncode == 0

    def export_watcher_is_running(self):
        if self.export_watcher_process and self.export_watcher_process.poll() is None:
            return True

        try:
            result = subprocess.run(
                ["pgrep", "-u", str(os.getuid()), "-f", "resolve_aac_export_watch.py"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            return False
        return result.returncode == 0

    def export_plugin_installed(self):
        return EXPORT_PLUGIN_TARGET_FILE.exists()

    def download_export_plugin(self, archive_path):
        with urllib.request.urlopen(EXPORT_PLUGIN_URL, timeout=30) as response:
            archive_path.write_bytes(response.read())

        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        if digest != EXPORT_PLUGIN_SHA256:
            raise RuntimeError(
                "Downloaded AAC export plugin checksum did not match the expected release."
            )

    def install_export_plugin_file(self, source_file):
        try:
            EXPORT_PLUGIN_TARGET_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, EXPORT_PLUGIN_TARGET_FILE)
            return
        except OSError:
            pass

        if not shutil.which("pkexec"):
            raise RuntimeError("Installing to /opt/resolve/IOPlugins requires pkexec or write access.")

        subprocess.run(["pkexec", "mkdir", "-p", str(EXPORT_PLUGIN_TARGET_DIR)], check=True)
        subprocess.run(["pkexec", "cp", str(source_file), str(EXPORT_PLUGIN_TARGET_FILE)], check=True)

    def install_export_plugin(self):
        if self.export_plugin_installed():
            self.notify("Resolve AAC Tools", "AAC export plugin is already installed.")
            return

        self.notify("Resolve AAC Tools", "Downloading AAC export plugin...")
        with tempfile.TemporaryDirectory(prefix="resolve-aac-export-plugin-") as raw_tmp:
            tmp = Path(raw_tmp)
            archive_path = tmp / "aac_encoder_plugin-linux-bundle.tar.gz"
            self.download_export_plugin(archive_path)

            with tarfile.open(archive_path, "r:gz") as archive:
                archive.extractall(tmp)

            source_file = tmp / EXPORT_PLUGIN_BUNDLE / "Contents" / "Linux-x86-64" / EXPORT_PLUGIN_FILE
            if not source_file.exists():
                raise RuntimeError("Downloaded AAC export plugin archive did not contain the plugin file.")

            self.install_export_plugin_file(source_file)

        self.notify("Resolve AAC Tools", "AAC export plugin installed. Restart Resolve to use it.")

    def uninstall_export_plugin(self):
        bundle_dir = EXPORT_PLUGIN_TARGET_DIR.parent.parent
        if not bundle_dir.exists():
            self.notify("Resolve AAC Tools", "AAC export plugin is not installed.")
            return

        try:
            shutil.rmtree(bundle_dir)
            self.notify("Resolve AAC Tools", "AAC export plugin uninstalled. Restart Resolve to finish unloading it.")
            return
        except OSError:
            pass

        if not shutil.which("pkexec"):
            raise RuntimeError("Uninstalling from /opt/resolve/IOPlugins requires pkexec or write access.")

        subprocess.run(["pkexec", "rm", "-rf", str(bundle_dir)], check=True)
        self.notify("Resolve AAC Tools", "AAC export plugin uninstalled. Restart Resolve to finish unloading it.")

    def resolve_font_wrapper_content(self):
        return """#!/usr/bin/env bash
set -euo pipefail

FONT_DIRS="/usr/share/fonts;/usr/local/share/fonts"

if [[ -d /usr/local/share/fonts ]]; then
  while IFS= read -r font_dir; do
    FONT_DIRS+=";$font_dir"
  done < <(find /usr/local/share/fonts -mindepth 1 -maxdepth 1 -type d | sort)
fi

if [[ -d "$HOME/.local/share/fonts" ]]; then
  FONT_DIRS+=";$HOME/.local/share/fonts"
fi

if [[ -d "$HOME/.fonts" ]]; then
  FONT_DIRS+=";$HOME/.fonts"
fi

export FUSION_FONTS="${FUSION_FONTS:+$FUSION_FONTS;}$FONT_DIRS"

exec /opt/resolve/bin/resolve "$@"
"""

    def resolve_desktop_entry(self):
        return f"""[Desktop Entry]
Version=1.0
Type=Application
Name=DaVinci Resolve
GenericName=DaVinci Resolve
Comment=Revolutionary new tools for editing, visual effects, color correction and professional audio post production, all in a single application!
Path=/opt/resolve/
Exec={RESOLVE_FONT_WRAPPER_PATH} %u
Terminal=false
MimeType=application/x-resolveproj;
Icon=/opt/resolve/graphics/DV_Resolve.png
StartupNotify=true
Name[en_US]=DaVinci Resolve
"""

    def resolve_font_fix_installed(self):
        if not RESOLVE_FONT_WRAPPER_PATH.exists() or not RESOLVE_DESKTOP_OVERRIDE_PATH.exists():
            return False

        try:
            desktop_text = RESOLVE_DESKTOP_OVERRIDE_PATH.read_text()
        except OSError:
            return False

        if f"Exec={RESOLVE_FONT_WRAPPER_PATH}" not in desktop_text:
            return False

        if not FUSION_PREFS_PATH.exists():
            return True

        try:
            prefs_text = FUSION_PREFS_PATH.read_text()
        except OSError:
            return False

        return all(path in prefs_text for path in self.fusion_font_paths())

    def write_resolve_font_wrapper(self):
        RESOLVE_FONT_WRAPPER_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESOLVE_FONT_WRAPPER_PATH.write_text(self.resolve_font_wrapper_content())
        RESOLVE_FONT_WRAPPER_PATH.chmod(0o755)

    def write_resolve_desktop_override(self):
        RESOLVE_DESKTOP_OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESOLVE_DESKTOP_OVERRIDE_PATH.write_text(self.resolve_desktop_entry())

    def update_fusion_font_prefs(self):
        if not FUSION_PREFS_PATH.exists():
            return

        lines = FUSION_PREFS_PATH.read_text().splitlines()
        replacement = f'\t\t\t\t["SystemFonts:"] = "$(FUSION_FONTS);{self.fusion_font_path_string()}",'
        for index, line in enumerate(lines):
            if '["SystemFonts:"]' in line:
                lines[index] = replacement
                FUSION_PREFS_PATH.write_text("\n".join(lines) + "\n")
                return

        raise RuntimeError(f"Could not find SystemFonts entry in {FUSION_PREFS_PATH}")

    def restore_fusion_font_prefs(self):
        if not FUSION_PREFS_PATH.exists():
            return

        lines = FUSION_PREFS_PATH.read_text().splitlines()
        replacement = '\t\t\t\t["SystemFonts:"] = "$(FUSION_FONTS)",'
        changed = False
        for index, line in enumerate(lines):
            if '["SystemFonts:"]' in line and any(path in line for path in self.fusion_font_paths()):
                lines[index] = replacement
                changed = True
                break

        if changed:
            FUSION_PREFS_PATH.write_text("\n".join(lines) + "\n")

    def rebuild_font_cache(self):
        cache_tool = shutil.which("fc-cache-64") or shutil.which("fc-cache")
        if cache_tool:
            subprocess.run(
                [cache_tool, "-f", "-v", "/usr/local/share/fonts"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

    def refresh_desktop_database(self):
        apps_dir = RESOLVE_DESKTOP_OVERRIDE_PATH.parent
        if shutil.which("update-desktop-database"):
            subprocess.run(
                ["update-desktop-database", str(apps_dir)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        if shutil.which("kbuildsycoca6"):
            subprocess.run(
                ["kbuildsycoca6"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

    def install_resolve_font_fix(self):
        self.write_resolve_font_wrapper()
        self.write_resolve_desktop_override()
        self.update_fusion_font_prefs()
        self.rebuild_font_cache()
        self.refresh_desktop_database()

    def uninstall_resolve_font_fix(self):
        removed = False
        try:
            if RESOLVE_FONT_WRAPPER_PATH.exists():
                RESOLVE_FONT_WRAPPER_PATH.unlink()
                removed = True
        except OSError as exc:
            raise RuntimeError(f"Could not remove {RESOLVE_FONT_WRAPPER_PATH}: {exc}") from exc

        if RESOLVE_DESKTOP_OVERRIDE_PATH.exists():
            try:
                desktop_text = RESOLVE_DESKTOP_OVERRIDE_PATH.read_text()
                if f"Exec={RESOLVE_FONT_WRAPPER_PATH}" in desktop_text:
                    RESOLVE_DESKTOP_OVERRIDE_PATH.unlink()
                    removed = True
            except OSError as exc:
                raise RuntimeError(f"Could not update {RESOLVE_DESKTOP_OVERRIDE_PATH}: {exc}") from exc

        self.restore_fusion_font_prefs()
        self.refresh_desktop_database()

        if removed:
            self.notify("Resolve AAC Tools", "Resolve font fix uninstalled. Restart Resolve to finish unloading it.")
        else:
            self.notify("Resolve AAC Tools", "Resolve font fix is not installed.")

    def start_resolve(self):
        if self.process and self.process.poll() is None:
            self.notify("Resolve AAC Tools", "Resolve launcher is already running.")
            return

        launcher = self.launcher_path()
        if not launcher.exists():
            self.error("Missing launcher", f"Could not find:\n{launcher}")
            return

        try:
            self.process = subprocess.Popen([str(launcher)], env=self.current_env())
        except Exception as exc:
            self.error("Could not start Resolve", str(exc))
            return

        self.notify("Resolve AAC Tools", "Started Resolve with MediaPool watcher.")
        self.update_status()

    def start_watcher_for_manual_resolve(self):
        watcher = self.watcher_path()
        if not watcher.exists():
            self.error("Missing watcher", f"Could not find:\n{watcher}")
            return

        if self.watcher_is_running():
            return

        try:
            STOP_PATH.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

        try:
            log_file = LOG_PATH.open("a")
            self.watcher_process = subprocess.Popen(
                self.watcher_args(),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=self.current_env(),
            )
        except Exception as exc:
            self.error("Could not start watcher", str(exc))
            return

        self.notify("Resolve AAC Tools", "Resolve detected. Started MediaPool watcher.")
        self.update_status()

    def stop_watcher(self):
        stop_script = self.stop_path()
        if not stop_script.exists():
            self.error("Missing stop script", f"Could not find:\n{stop_script}")
            return

        try:
            subprocess.run([sys.executable, str(stop_script)], check=False)
        except Exception as exc:
            self.error("Could not stop watcher", str(exc))
            return

        self.notify("Resolve AAC Tools", "Watcher stop requested.")
        self.update_status()

    def start_export_watcher(self, notify=True):
        watcher = self.export_watcher_path()
        if not watcher.exists():
            self.error("Missing export watcher", f"Could not find:\n{watcher}")
            return

        if self.export_watcher_is_running():
            return

        try:
            EXPORT_WATCH_STOP_PATH.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

        try:
            self.export_watcher_log_file = EXPORT_WATCH_LOG_PATH.open("a")
            self.export_watcher_process = subprocess.Popen(
                self.export_watcher_args(),
                stdout=self.export_watcher_log_file,
                stderr=subprocess.STDOUT,
                env=self.current_env(),
            )
        except Exception as exc:
            if self.export_watcher_log_file:
                self.export_watcher_log_file.close()
                self.export_watcher_log_file = None
            self.error("Could not start export remux watcher", str(exc))
            return

        if notify:
            self.notify("Resolve AAC Tools", "Export remux watcher started.")
        self.update_status()

    def stop_export_watcher(self, notify=True):
        try:
            EXPORT_WATCH_STOP_PATH.write_text("stop\n")
        except OSError:
            pass

        if self.export_watcher_process and self.export_watcher_process.poll() is None:
            self.export_watcher_process.terminate()

        self.export_watcher_process = None
        if self.export_watcher_log_file:
            self.export_watcher_log_file.close()
            self.export_watcher_log_file = None

        if notify:
            self.notify("Resolve AAC Tools", "Export remux watcher stop requested.")
        self.update_status()

    def set_use_cache(self, enabled):
        watcher_was_running = self.watcher_is_running()
        self.config["use_cache"] = bool(enabled)
        save_config(self.config)
        if watcher_was_running and self.resolve_is_running():
            self.stop_watcher()
            QTimer.singleShot(1000, self.start_watcher_for_manual_resolve)
            self.notify("Resolve AAC Tools", "Restarting watcher with updated output settings.")
        self.update_status()

    def set_watch_manual_resolve(self, enabled):
        self.config["watch_manual_resolve"] = bool(enabled)
        save_config(self.config)
        self.update_status()

    def set_remux_exports(self, enabled):
        self.config["remux_exports"] = bool(enabled)
        save_config(self.config)
        if enabled:
            self.start_export_watcher()
        else:
            self.stop_export_watcher()
        self.update_status()

    def confirm_uninstall(self, title, message):
        result = QMessageBox.question(
            None,
            title,
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return result == QMessageBox.Yes

    def handle_export_plugin_action(self):
        if self.export_plugin_installed():
            if self.confirm_uninstall(
                "Uninstall AAC export plugin?",
                "Remove the AAC export plugin from Resolve's IOPlugins folder?",
            ):
                self.handle_uninstall_export_plugin_action()
            else:
                self.update_export_plugin_action()
            return

        try:
            self.install_export_plugin()
        except Exception as exc:
            self.error("Could not install AAC export plugin", str(exc))

        self.update_export_plugin_action()

    def handle_uninstall_export_plugin_action(self):
        try:
            self.uninstall_export_plugin()
        except Exception as exc:
            self.error("Could not uninstall AAC export plugin", str(exc))

        self.update_export_plugin_action()

    def handle_resolve_font_action(self):
        if self.resolve_font_fix_installed():
            if self.confirm_uninstall(
                "Uninstall Resolve font fix?",
                "Remove the Resolve font wrapper and desktop override?",
            ):
                self.handle_uninstall_resolve_font_action()
            else:
                self.update_resolve_font_action()
            return

        try:
            self.install_resolve_font_fix()
        except Exception as exc:
            self.update_resolve_font_action()
            self.error("Could not apply Resolve font fix", str(exc))
            return

        self.notify("Resolve AAC Tools", "Resolve font fix applied. Restart Resolve to use it.")
        self.update_resolve_font_action()

    def handle_uninstall_resolve_font_action(self):
        try:
            self.uninstall_resolve_font_fix()
        except Exception as exc:
            self.error("Could not uninstall Resolve font fix", str(exc))

        self.update_resolve_font_action()

    def set_autostart(self, enabled):
        try:
            if enabled:
                write_autostart_file()
            else:
                remove_autostart_file()
        except Exception as exc:
            self.autostart_action.blockSignals(True)
            self.autostart_action.setChecked(autostart_enabled())
            self.autostart_action.blockSignals(False)
            self.error("Could not update autostart", str(exc))

    def choose_cache_folder(self):
        current = str(Path(self.config["cache_dir"]).expanduser())
        chosen = QFileDialog.getExistingDirectory(None, "Choose cache folder", current)
        if not chosen:
            return

        self.config["cache_dir"] = chosen
        self.config["use_cache"] = True
        self.cache_action.setChecked(True)
        save_config(self.config)
        self.update_status()

    def open_path(self, path):
        path = path.expanduser()
        if path == LOG_PATH and not path.exists():
            self.notify("Resolve AAC Tools", "No launcher log exists yet.")
            return
        if path != LOG_PATH:
            path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def update_status(self):
        launcher_running = self.process is not None and self.process.poll() is None
        watcher_running = self.watcher_is_running()
        export_watcher_running = self.export_watcher_is_running()
        mode = "cache folder" if self.config["use_cache"] else "source folders"
        if launcher_running:
            status = "Resolve launcher running"
        elif watcher_running:
            status = "Watcher running"
        elif export_watcher_running:
            status = "Export remux watcher running"
        else:
            status = "Stopped"
        export_status = "export remux on" if self.config["remux_exports"] else "export remux off"
        self.status_action.setText(f"{status} - output: {mode} - {export_status}")
        self.stop_action.setEnabled(True)
        self.open_cache_action.setEnabled(bool(self.config["use_cache"]))
        self.remux_exports_action.blockSignals(True)
        self.remux_exports_action.setChecked(bool(self.config["remux_exports"]))
        self.remux_exports_action.blockSignals(False)
        self.tray.setToolTip(
            "\n".join([
                "Resolve AAC Tools",
                f"Status: {status}",
                f"Output: {mode}",
                f"Export remux: {'on' if self.config['remux_exports'] else 'off'}",
                "Left-click: start Resolve + watcher",
                "Right-click: settings",
            ])
        )
        self.update_export_plugin_action()
        self.update_resolve_font_action()

    def update_export_plugin_action(self):
        installed = self.export_plugin_installed()
        self.export_plugin_action.blockSignals(True)
        self.export_plugin_action.setText(
            "AAC export plugin: ✓ Installed" if installed else "AAC export plugin: Install"
        )
        self.export_plugin_action.blockSignals(False)

    def update_resolve_font_action(self):
        installed = self.resolve_font_fix_installed()
        self.resolve_font_action.blockSignals(True)
        self.resolve_font_action.setText(
            "Resolve font fix: ✓ Installed" if installed else "Resolve font fix: Install"
        )
        self.resolve_font_action.blockSignals(False)

    def consume_start_request(self):
        if not START_REQUEST_PATH.exists():
            return

        try:
            START_REQUEST_PATH.unlink()
        except OSError:
            pass

        self.start_resolve()

    def tick(self):
        if self.config["remux_exports"] and not self.export_watcher_is_running():
            self.start_export_watcher(notify=False)
        self.update_status()
        self.consume_start_request()

    def check_manual_resolve(self):
        if not self.config["watch_manual_resolve"]:
            self.manual_resolve_was_running = self.resolve_is_running()
            return

        if self.process and self.process.poll() is None:
            self.manual_resolve_was_running = True
            return

        resolve_running = self.resolve_is_running()
        if resolve_running:
            self.start_watcher_for_manual_resolve()
        elif self.manual_resolve_was_running and self.watcher_process:
            self.stop_watcher()

        self.manual_resolve_was_running = resolve_running

    def on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.start_resolve()

    def quit(self):
        if self.export_watcher_log_file:
            self.export_watcher_log_file.close()
        save_config(self.config)
        self.tray.hide()
        self.app.quit()

    def run(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.error("No system tray", "This desktop session does not expose a system tray.")
        return self.app.exec()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(ResolveAacTray(start_resolve=args.start_resolve).run())
