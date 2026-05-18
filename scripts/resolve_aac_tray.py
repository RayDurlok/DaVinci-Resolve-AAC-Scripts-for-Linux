#!/usr/bin/env python3

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    from PySide6.QtCore import QTimer, QUrl
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
MANUAL_RESOLVE_CHECK_MS = 10000


def load_config():
    defaults = {
        "use_cache": True,
        "cache_dir": str(DEFAULT_CACHE_DIR),
        "watch_manual_resolve": True,
    }
    try:
        data = json.loads(CONFIG_PATH.read_text())
    except Exception:
        return defaults

    defaults.update({key: data[key] for key in defaults if key in data})
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


class ResolveAacTray:
    def __init__(self, start_resolve=False):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.config = load_config()
        self.process = None
        self.watcher_process = None
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

    def current_env(self):
        env = os.environ.copy()
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

    def set_use_cache(self, enabled):
        self.config["use_cache"] = bool(enabled)
        save_config(self.config)
        self.update_status()

    def set_watch_manual_resolve(self, enabled):
        self.config["watch_manual_resolve"] = bool(enabled)
        save_config(self.config)
        self.update_status()

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
        mode = "cache folder" if self.config["use_cache"] else "source folders"
        if launcher_running:
            status = "Resolve launcher running"
        elif watcher_running:
            status = "Watcher running"
        else:
            status = "Stopped"
        self.status_action.setText(f"{status} - output: {mode}")
        self.stop_action.setEnabled(True)
        self.open_cache_action.setEnabled(bool(self.config["use_cache"]))
        self.tray.setToolTip(
            "\n".join([
                "Resolve AAC Tools",
                f"Status: {status}",
                f"Output: {mode}",
                "Left-click: start Resolve + watcher",
                "Right-click: settings",
            ])
        )

    def consume_start_request(self):
        if not START_REQUEST_PATH.exists():
            return

        try:
            START_REQUEST_PATH.unlink()
        except OSError:
            pass

        self.start_resolve()

    def tick(self):
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
