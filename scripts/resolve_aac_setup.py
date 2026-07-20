#!/usr/bin/env python3

from __future__ import annotations

import os
import shutil
import sys
import threading
from pathlib import Path

try:
    from PySide6.QtCore import Property, QEasingCurve, QEvent, QPropertyAnimation, QSize, Qt, Signal
    from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import (
        QAbstractButton,
        QApplication,
        QFileDialog,
        QFrame,
        QGraphicsDropShadowEffect,
        QGraphicsOpacityEffect,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QStackedWidget,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    print("Resolve AAC Settings requires PySide6.", file=sys.stderr)
    print("Install it with your distro package manager, for example python3-pyside6.", file=sys.stderr)
    raise SystemExit(2)

from resolve_aac_config import APP_VERSION, load_config, save_config


SCRIPT_DIR = Path(__file__).resolve().parent
RESOLVE_SCRIPTS_DIR = Path.home() / ".local" / "share" / "DaVinciResolve" / "Fusion" / "Scripts" / "Edit"
RESOLVE_AAC_SCRIPTS_DIR = RESOLVE_SCRIPTS_DIR / "DaVinci Resolve Toolkit"
SCRIPT_LINKS = {
    "Resolve AAC Current Clip.py": "resolve_aac_remux_current.py",
    "Resolve AAC Timeline Watch.py": "resolve_aac_timeline_watch.py",
    "Stop Resolve AAC Timeline Watch.py": "resolve_aac_timeline_watch_stop.py",
    "Resolve AAC MediaPool Watch.py": "resolve_aac_mediapool_watch.py",
    "Stop Resolve AAC MediaPool Watch.py": "resolve_aac_mediapool_watch_stop.py",
    "Restore Original Sources.py": "resolve_aac_restore.py",
    "Remux All AAC Media.py": "resolve_aac_remux_all.py",
}

# Two palettes; the active one is chosen from the system colour scheme at
# startup (and re-applied live if the user flips dark/light while it is open).
DARK = {
    "BG": "#0E1116", "SURFACE": "#171C23", "SURFACE2": "#1E242D", "BORDER": "#252C36",
    "TEXT": "#E7ECF3", "MUTED": "#8A94A6", "ACCENT": "#4C8BF5", "ACCENT_HOVER": "#5F99F7",
    "GOOD": "#3DD68C", "WARN": "#F0803C", "OFF_TRACK": "#39424E",
}
LIGHT = {
    "BG": "#F5F6F8", "SURFACE": "#FFFFFF", "SURFACE2": "#EEF0F3", "BORDER": "#DCE0E6",
    "TEXT": "#1C2230", "MUTED": "#606B7A", "ACCENT": "#3B7DF0", "ACCENT_HOVER": "#2F6BD8",
    "GOOD": "#1E9E57", "WARN": "#C96A22", "OFF_TRACK": "#C6CCD6",
}

# Active palette; filled in by set_palette() (defaults to dark so importing is safe).
BG = SURFACE = SURFACE2 = BORDER = TEXT = MUTED = ACCENT = ACCENT_HOVER = GOOD = WARN = OFF_TRACK = ""


def set_palette(palette):
    global BG, SURFACE, SURFACE2, BORDER, TEXT, MUTED, ACCENT, ACCENT_HOVER, GOOD, WARN, OFF_TRACK
    BG, SURFACE, SURFACE2, BORDER = palette["BG"], palette["SURFACE"], palette["SURFACE2"], palette["BORDER"]
    TEXT, MUTED = palette["TEXT"], palette["MUTED"]
    ACCENT, ACCENT_HOVER = palette["ACCENT"], palette["ACCENT_HOVER"]
    GOOD, WARN, OFF_TRACK = palette["GOOD"], palette["WARN"], palette["OFF_TRACK"]


def system_is_light(app):
    # RESOLVE_AAC_FORCE_SCHEME=light|dark overrides detection (handy for testing).
    forced = os.environ.get("RESOLVE_AAC_FORCE_SCHEME", "").strip().lower()
    if forced in ("light", "dark"):
        return forced == "light"
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Light
    except Exception:
        return False


def apply_palette(app):
    set_palette(LIGHT if system_is_light(app) else DARK)


set_palette(DARK)


ICON_PATHS = [
    Path("/usr/share/icons/hicolor/512x512/apps/io.github.raydurlok.ResolveAacTools.png"),
    SCRIPT_DIR / "resolve-aac-tools-icon-512.png",
    SCRIPT_DIR.parent / "resolve-aac-tools-icon-512.png",
    SCRIPT_DIR / "resolve-aac-tools-icon.png",
    SCRIPT_DIR.parent / "resolve-aac-tools-icon.png",
]


def app_icon():
    for path in ICON_PATHS:
        if not path.exists():
            continue
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            continue
        # A huge source (e.g. 3000x3000) can overwhelm the system tray over DBus
        # and take down plasmashell, cap it to a sane size.
        if max(pixmap.width(), pixmap.height()) > 256:
            pixmap = pixmap.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return QIcon(pixmap)
    return QIcon()


def resolve_menu_scripts_installed():
    return all((RESOLVE_AAC_SCRIPTS_DIR / name).is_symlink() for name in SCRIPT_LINKS)


def install_resolve_menu_scripts():
    RESOLVE_AAC_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    for link_name, target_name in SCRIPT_LINKS.items():
        source = SCRIPT_DIR / target_name
        target = RESOLVE_AAC_SCRIPTS_DIR / link_name
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(source)


def remove_resolve_menu_scripts():
    for link_name in SCRIPT_LINKS:
        target = RESOLVE_AAC_SCRIPTS_DIR / link_name
        try:
            if target.exists() or target.is_symlink():
                target.unlink()
        except OSError:
            pass
    try:
        RESOLVE_AAC_SCRIPTS_DIR.rmdir()
    except OSError:
        pass


def tray_helper():
    """Reuse the tray's operations (font fix, export plugin, updater) without a
    running tray and without duplicating the logic. The methods we call only
    touch files/subprocess, so an un-__init__'d instance with stubbed notify/
    error and a loaded config is enough."""
    from resolve_aac_config import load_config
    from resolve_aac_tray import ResolveAacTray
    helper = ResolveAacTray.__new__(ResolveAacTray)
    helper.notify = lambda *args, **kwargs: None
    helper.error = lambda *args, **kwargs: None
    helper.config = load_config()
    return helper


_RESOLVE_INFO_CACHE = None  # (stat_key, version, edition)


def _resolve_bin_stat_key():
    try:
        st = os.stat("/opt/resolve/bin/resolve")
        return (int(st.st_mtime), st.st_size)
    except OSError:
        return None


def detect_resolve_info():
    """Best-effort (version, edition) for the installed DaVinci Resolve.

    version is like "21.0.2" (or None), edition is "Studio"/"Free"/None.
    Cached against the binary's mtime/size, so the expensive strings(1) scan of
    the ~600 MB Resolve binary only re-runs when it actually changes.
    """
    global _RESOLVE_INFO_CACHE
    stat_key = _resolve_bin_stat_key()
    if _RESOLVE_INFO_CACHE is not None and _RESOLVE_INFO_CACHE[0] == stat_key:
        return _RESOLVE_INFO_CACHE[1], _RESOLVE_INFO_CACHE[2]
    version = None
    edition = None
    resolve_bin = Path("/opt/resolve/bin/resolve")
    if resolve_bin.exists() and shutil.which("strings"):
        try:
            import re
            import subprocess
            out = subprocess.run(
                ["strings", str(resolve_bin)],
                capture_output=True, text=True, timeout=8,
            ).stdout
            # The binary carries a clean marker like "21.0.2.0004_studio".
            marker = re.search(r"\b(\d+\.\d+\.\d+)\.\d+_(studio|free)\b", out)
            if marker:
                version = marker.group(1)
                edition = marker.group(2).capitalize()
            else:
                # Fallback: major.minor + large build, avoiding frame rates.
                best = None
                for match in re.finditer(r"\b((?:1[5-9]|2[0-2])\.\d+)\.(\d{4,})\b", out):
                    parts = tuple(int(x) for x in match.group(1).split("."))
                    if best is None or parts > best[0]:
                        best = (parts, match.group(1))
                if best:
                    version = best[1]
        except Exception:
            pass
    if edition is None:
        # A Studio license file is a reliable edition marker.
        try:
            license_dir = Path("/opt/resolve/.license")
            if license_dir.exists() and any(license_dir.glob("*davinciresolvestudio*")):
                edition = "Studio"
        except Exception:
            pass
    _RESOLVE_INFO_CACHE = (stat_key, version, edition)
    return version, edition


def cached_resolve_info():
    """(version, edition) if a fresh cached result exists for the current binary."""
    if _RESOLVE_INFO_CACHE is not None and _RESOLVE_INFO_CACHE[0] == _resolve_bin_stat_key():
        return _RESOLVE_INFO_CACHE[1], _RESOLVE_INFO_CACHE[2]
    return None


class ToggleSwitch(QAbstractButton):
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(52, 30)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def get_knob(self):
        return self._pos

    def set_knob(self, value):
        self._pos = value
        self.update()

    knob = Property(float, get_knob, set_knob)

    def sizeHint(self):
        return QSize(52, 30)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        off = QColor(OFF_TRACK)
        on = QColor(ACCENT)
        amount = self._pos
        color = QColor(
            int(off.red() + (on.red() - off.red()) * amount),
            int(off.green() + (on.green() - off.green()) * amount),
            int(off.blue() + (on.blue() - off.blue()) * amount),
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        diameter = rect.height() - 6
        x = rect.left() + 3 + (rect.width() - diameter - 6) * self._pos
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(int(x), rect.top() + 3, int(diameter), int(diameter))


def make_label(text, size, weight=QFont.Normal, color=None):
    label = QLabel(text)
    font = QFont("Inter")
    font.setPixelSize(size)
    font.setWeight(weight)
    label.setFont(font)
    label.setStyleSheet(f"color:{color or TEXT};")
    label.setWordWrap(True)
    return label


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setColor(QColor(0, 0, 0, 120))
        shadow.setOffset(0, 6)
        self.setGraphicsEffect(shadow)


class SettingRow(QFrame):
    def __init__(self, title, description, trailing):
        super().__init__()
        self.setObjectName("row")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(16)
        copy = QVBoxLayout()
        copy.setSpacing(2)
        copy.addWidget(make_label(title, 16, QFont.DemiBold))
        copy.addWidget(make_label(description, 13, QFont.Normal, MUTED))
        layout.addLayout(copy, 1)
        layout.addWidget(trailing, 0, Qt.AlignRight | Qt.AlignVCenter)


class StepDots(QWidget):
    def __init__(self, count):
        super().__init__()
        self.count = count
        self.index = 0
        self.setFixedHeight(10)

    def set_index(self, index):
        self.index = index
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        x = 0
        for index in range(self.count):
            active = index == self.index
            painter.setBrush(QColor(ACCENT if active else BORDER))
            width = 22 if active else 8
            painter.drawRoundedRect(x, 1, width, 8, 4, 4)
            x += width + 8


class SetupWindow(QWidget):
    settings_saved = Signal(dict)
    resolve_info_ready = Signal(object)

    def __init__(self, parent=None, first_run=False):
        super().__init__(parent)
        self.cfg = load_config()
        self.first_run = first_run
        self._recheck_in_flight = False
        self.resolve_info_ready.connect(self._apply_resolve_info)
        self.setWindowTitle("DaVinci Resolve Toolkit")
        _icon = app_icon()
        if not _icon.isNull():
            self.setWindowIcon(_icon)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.resize(int(self.cfg.get("window_width", 880)), int(self.cfg.get("window_height", 600)))
        self.setMinimumSize(760, 560)
        self.setStyleSheet(self.qss())

        # Follow the system dark/light scheme live while the window is open.
        try:
            QApplication.instance().styleHints().colorSchemeChanged.connect(self.on_scheme_changed)
        except Exception:
            pass

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 34, 40, 30)
        root.setSpacing(0)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        self.title = make_label("Welcome", 30, QFont.DemiBold)
        self.subtitle = make_label("Let's set up your AAC workflow.", 15, QFont.Normal, MUTED)
        title_box.addWidget(self.title)
        title_box.addWidget(self.subtitle)
        header.addLayout(title_box, 1)
        self.dots = StepDots(5)
        header.addWidget(self.dots, 0, Qt.AlignRight | Qt.AlignTop)
        root.addLayout(header)
        root.addSpacing(26)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.page_welcome())
        self.stack.addWidget(self.page_toggles())
        self.stack.addWidget(self.page_paths())
        self.stack.addWidget(self.page_export())
        self.stack.addWidget(self.page_scripts())
        root.addWidget(self.stack, 1)
        root.addSpacing(22)

        footer = QHBoxLayout()
        self.back_btn = QPushButton("Back")
        self.back_btn.setObjectName("ghost")
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.clicked.connect(lambda: self.go(-1))
        self.next_btn = QPushButton("Continue")
        self.next_btn.setObjectName("primary")
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.clicked.connect(lambda: self.go(1))
        footer.addWidget(self.back_btn)
        footer.addStretch(1)
        footer.addWidget(self.next_btn)
        root.addLayout(footer)

        self.titles = [
            ("Welcome", "Configure the toolkit here, or from the tray icon. Click Continue to begin."),
            ("Preferences", "General behaviour and startup options."),
            ("Paths", "Choose how remuxed files are stored."),
            ("Export", "Two ways to get web-friendly AAC in your renders."),
            ("Extras", ""),
        ]
        self.index = 0
        self.sync()

    def page_welcome(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        card = Card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(26, 22, 26, 22)
        card_layout.setSpacing(12)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.addWidget(make_label("DaVinci Resolve Toolkit", 20, QFont.DemiBold))
        title_row.addWidget(make_label(f"v{APP_VERSION}", 13, QFont.Normal, MUTED))
        title_row.addStretch(1)
        card_layout.addLayout(title_row)
        card_layout.addWidget(make_label(
            "Resolve on Linux can't import AAC audio. It converts AAC to PCM that Resolve can "
            "read on import, plus a few more fixes, all from the tray.",
            14,
            QFont.Normal,
            MUTED,
        ))
        resolve_ok = Path("/opt/resolve/bin/resolve").exists()

        # Studio warning, hidden while detecting; shown only when Resolve is
        # missing or turns out to be the free edition (decided by the async check).
        self.studio_warning = make_label(
            "Requires DaVinci Resolve Studio, the free version doesn't expose the scripting API these tools use.",
            13,
            QFont.DemiBold,
            WARN,
        )
        card_layout.addWidget(self.studio_warning)
        self.studio_warning.setVisible(not resolve_ok)

        resolve_row, self.resolve_desc_label, _resolve_badge = self._status_row(
            "DaVinci Resolve",
            "Detecting version…" if resolve_ok else "Not found in /opt/resolve",
            "Ready" if resolve_ok else "Missing",
            GOOD if resolve_ok else WARN,
        )
        card_layout.addWidget(resolve_row)
        card_layout.addWidget(self.check_row("ffmpeg", "Used for remuxing AAC audio", shutil.which("ffmpeg") is not None))

        # Version/edition detection scans the large Resolve binary, so keep it off
        # the UI thread and cached against the binary's mtime (see detect_resolve_info).
        if resolve_ok:
            self._refresh_resolve_info()

        update_btn = QPushButton("Update DaVinci Resolve from a ZIP in Downloads")
        update_btn.setObjectName("ghost")
        update_btn.setCursor(Qt.PointingHandCursor)
        update_btn.clicked.connect(self.update_resolve)
        card_layout.addWidget(update_btn, 0, Qt.AlignLeft)

        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def update_resolve(self):
        try:
            tray_helper().launch_resolve_updater()
        except Exception as exc:
            QMessageBox.warning(self, "DaVinci Resolve Toolkit", f"Could not launch the Resolve updater:\n{exc}")
            return
        # The installer runs in its own terminal; the version refreshes by itself
        # when you return to this window (changeEvent -> _refresh_resolve_info).
        try:
            self.resolve_desc_label.setText("Updating Resolve, re-checks when you return here…")
        except (RuntimeError, AttributeError):
            pass

    def changeEvent(self, event):
        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            self._refresh_resolve_info()
        super().changeEvent(event)

    def _refresh_resolve_info(self):
        # Cheap on every focus: a stat() tells us whether the ~600 MB Resolve
        # binary changed. Only then do we re-run the expensive strings() scan, so
        # tool updates, manual updates, and external changes all get picked up.
        if self._recheck_in_flight or not hasattr(self, "resolve_desc_label"):
            return
        if not Path("/opt/resolve/bin/resolve").exists():
            return
        cached = cached_resolve_info()
        if cached is not None:
            self._apply_resolve_info(cached)
            return
        self._recheck_in_flight = True
        try:
            self.resolve_desc_label.setText("Detecting version…")
        except (RuntimeError, AttributeError):
            pass
        threading.Thread(target=self._detect_resolve_async, daemon=True).start()

    def _detect_resolve_async(self):
        self.resolve_info_ready.emit(detect_resolve_info())

    def _apply_resolve_info(self, info):
        version, edition = info
        if edition and version:
            text = f"{edition} {version} detected"
        elif version:
            text = f"Version {version} detected"
        else:
            text = "Detected in /opt/resolve"
        try:
            self.resolve_desc_label.setText(text)
            self.studio_warning.setVisible(edition == "Free")
        except (RuntimeError, AttributeError):
            pass  # window/labels already gone
        self._recheck_in_flight = False

    def check_row(self, title, description, ok):
        row = QFrame()
        row.setObjectName("row")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(18, 12, 18, 12)
        copy = QVBoxLayout()
        copy.setSpacing(1)
        copy.addWidget(make_label(title, 15, QFont.DemiBold))
        copy.addWidget(make_label(description, 12, QFont.Normal, MUTED))
        layout.addLayout(copy, 1)
        layout.addWidget(make_label("Ready" if ok else "Missing", 14, QFont.DemiBold, GOOD if ok else WARN))
        return row

    def _status_row(self, title, description, badge_text, badge_color):
        row = QFrame()
        row.setObjectName("row")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(18, 12, 18, 12)
        copy = QVBoxLayout()
        copy.setSpacing(1)
        copy.addWidget(make_label(title, 15, QFont.DemiBold))
        desc_label = make_label(description, 12, QFont.Normal, MUTED)
        copy.addWidget(desc_label)
        layout.addLayout(copy, 1)
        badge_label = make_label(badge_text, 14, QFont.DemiBold, badge_color)
        layout.addWidget(badge_label)
        return row, desc_label, badge_label

    def _config_toggle_row(self, key, title, description):
        toggle = ToggleSwitch(bool(self.cfg.get(key)))
        toggle.toggled.connect(lambda value, item=key: self.cfg.__setitem__(item, bool(value)))
        return SettingRow(title, description, toggle)

    def page_toggles(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        card = Card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(6, 6, 6, 6)
        card_layout.setSpacing(0)

        rows = [
            self._config_toggle_row(
                "watch_manual_resolve", "Auto-remux AAC on import",
                "Automatically remux AAC-audio video when you import it into the media pool."),
            self._config_toggle_row(
                "intercept_deliver_browse", "Native KDE file dialogs",
                "Use native KDE dialogs for standard file pickers and the Deliver destination. Relink stays in Resolve."),
        ]

        # Autostart is file-based (XDG autostart), separate from config.json.
        try:
            from resolve_aac_tray import autostart_enabled
            autostart_on = autostart_enabled()
        except Exception:
            autostart_on = False
        autostart_toggle = ToggleSwitch(autostart_on)
        autostart_toggle.toggled.connect(self.set_autostart)
        rows.append(SettingRow(
            "Start Toolkit at login",
            "Launch the toolkit automatically after you log in.",
            autostart_toggle,
        ))

        rows.append(self._config_toggle_row(
            "logging_enabled", "Enable logging",
            "Write diagnostic logs to /tmp for troubleshooting."))

        # Mute notifications stays last.
        rows.append(self._config_toggle_row(
            "mute_notifications", "Mute notifications",
            "Keep the workflow quiet, errors still show up."))

        for index, row in enumerate(rows):
            card_layout.addWidget(row)
            if index < len(rows) - 1:
                sep = QFrame()
                sep.setObjectName("sep")
                sep.setFixedHeight(1)
                card_layout.addWidget(sep)

        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def set_autostart(self, enabled):
        try:
            from resolve_aac_tray import remove_autostart_file, write_autostart_file
            if enabled:
                write_autostart_file()
            else:
                remove_autostart_file()
        except Exception as exc:
            QMessageBox.warning(self, "DaVinci Resolve Toolkit", f"Could not update autostart:\n{exc}")

    def page_paths(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        card = Card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 22, 24, 22)
        card_layout.setSpacing(12)
        card_layout.addWidget(make_label("Cache folder", 18, QFont.DemiBold))
        card_layout.addWidget(make_label(
            "When enabled, remuxed files go into one cache folder instead of sitting beside your source media.",
            13,
            QFont.Normal,
            MUTED,
        ))
        path_row = QHBoxLayout()
        self.cache_edit = QLineEdit(str(self.cfg.get("cache_dir", "")))
        self.cache_edit.setObjectName("input")
        self.cache_edit.textChanged.connect(lambda text: self.cfg.__setitem__("cache_dir", text))
        browse = QPushButton("Browse")
        browse.setObjectName("ghost")
        browse.setCursor(Qt.PointingHandCursor)
        browse.clicked.connect(self.choose_cache_folder)
        path_row.addWidget(self.cache_edit, 1)
        path_row.addWidget(browse)
        card_layout.addLayout(path_row)
        self.use_cache_toggle = ToggleSwitch(bool(self.cfg.get("use_cache")))
        self.use_cache_toggle.toggled.connect(lambda value: self.cfg.__setitem__("use_cache", bool(value)))
        card_layout.addWidget(SettingRow("Use a single cache folder", "Keep source folders untouched.", self.use_cache_toggle))
        self.cache_off_hint = make_label(
            "When off, remuxed media are written to a folder right next to the source files.",
            13,
            QFont.Normal,
            MUTED,
        )
        card_layout.addWidget(self.cache_off_hint)
        self.use_cache_toggle.toggled.connect(lambda on: self.cache_off_hint.setVisible(not on))
        self.cache_off_hint.setVisible(not bool(self.cfg.get("use_cache")))
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def page_export(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # 1) Export remux, the default, ffmpeg-based approach.
        remux_card = Card()
        remux_layout = QVBoxLayout(remux_card)
        remux_layout.setContentsMargins(24, 22, 24, 22)
        remux_layout.setSpacing(6)
        remux_layout.addWidget(make_label("Export remux (recommended)", 18, QFont.DemiBold))
        remux_layout.addWidget(make_label(
            "Converts FLAC and PCM audio in your renders to web-friendly AAC, replacing the "
            "file in place.",
            13,
            QFont.Normal,
            MUTED,
        ))
        remux_layout.addSpacing(4)
        remux_toggle = ToggleSwitch(bool(self.cfg.get("remux_exports")))
        remux_toggle.toggled.connect(lambda value: self.cfg.__setitem__("remux_exports", bool(value)))
        remux_layout.addWidget(SettingRow(
            "Remux all exports to web-friendly AAC",
            "Runs automatically after each render.",
            remux_toggle,
        ))
        layout.addWidget(remux_card)

        # 2) AAC export plugin, the alternative, Resolve 20 only.
        plugin_card = Card()
        plugin_layout = QVBoxLayout(plugin_card)
        plugin_layout.setContentsMargins(24, 22, 24, 22)
        plugin_layout.setSpacing(12)
        plugin_layout.addWidget(make_label("AAC export plugin (Resolve 20 only)", 18, QFont.DemiBold))
        plugin_layout.addWidget(make_label(
            "Installs an encoder plugin so Resolve exports AAC directly. "
            "Resolve 20 only, restart Resolve after changing this.",
            13,
            QFont.Normal,
            MUTED,
        ))
        plugin_layout.addWidget(make_label(
            "Third-party plugin by Toxblh, installed at your own risk, not maintained by us. "
            "Source: github.com/Toxblh/davinci-linux-aac-codec",
            12,
            QFont.Normal,
            MUTED,
        ))
        self.plugin_status = make_label("", 13, QFont.Normal, MUTED)
        self.plugin_btn = QPushButton()
        self.plugin_btn.setObjectName("primary")
        self.plugin_btn.setCursor(Qt.PointingHandCursor)
        self.plugin_btn.clicked.connect(self.toggle_export_plugin)
        plugin_layout.addWidget(self.plugin_btn, 0, Qt.AlignLeft)
        plugin_layout.addWidget(self.plugin_status)
        self.update_plugin_state()
        layout.addWidget(plugin_card)

        layout.addStretch(1)
        return page

    def page_scripts(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        card = Card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 16, 24, 16)
        card_layout.setSpacing(10)
        card_layout.addWidget(make_label("Resolve menu scripts", 18, QFont.DemiBold))
        card_layout.addWidget(make_label(
            "Add shortcuts under Workspace → Scripts in Resolve: remux the current clip or all "
            "media pool clips, restore original sources, and start or stop the watchers.",
            13,
            QFont.Normal,
            MUTED,
        ))
        self.script_status = make_label("", 13, QFont.Normal, MUTED)
        self.script_btn = QPushButton()
        self.script_btn.setObjectName("primary")
        self.script_btn.setCursor(Qt.PointingHandCursor)
        self.script_btn.clicked.connect(self.toggle_resolve_menu_scripts)
        card_layout.addWidget(self.script_btn, 0, Qt.AlignLeft)
        card_layout.addWidget(self.script_status)
        self.update_script_state()
        layout.addWidget(card)

        font_card = Card()
        font_layout = QVBoxLayout(font_card)
        font_layout.setContentsMargins(24, 16, 24, 16)
        font_layout.setSpacing(10)
        font_layout.addWidget(make_label("Resolve font fix", 18, QFont.DemiBold))
        font_layout.addWidget(make_label(
            "Let Resolve and Fusion use fonts from /usr/local/share/fonts and other user folders.",
            13,
            QFont.Normal,
            MUTED,
        ))
        self.font_status = make_label("", 13, QFont.Normal, MUTED)
        self.font_btn = QPushButton()
        self.font_btn.setObjectName("primary")
        self.font_btn.setCursor(Qt.PointingHandCursor)
        self.font_btn.clicked.connect(self.toggle_font_fix)
        font_layout.addWidget(self.font_btn, 0, Qt.AlignLeft)
        font_layout.addWidget(self.font_status)
        self.update_font_state()
        layout.addWidget(font_card)

        layout.addStretch(1)
        return page

    def choose_cache_folder(self):
        current = str(Path(self.cfg.get("cache_dir", "")).expanduser())
        chosen = QFileDialog.getExistingDirectory(self, "Choose cache folder", current)
        if chosen:
            self.cache_edit.setText(chosen)
            self.cfg["cache_dir"] = chosen
            self.cfg["use_cache"] = True
            self.use_cache_toggle.setChecked(True)

    def toggle_resolve_menu_scripts(self):
        try:
            if resolve_menu_scripts_installed():
                remove_resolve_menu_scripts()
            else:
                install_resolve_menu_scripts()
        except OSError as exc:
            QMessageBox.warning(self, "DaVinci Resolve Toolkit", f"Could not update Resolve menu scripts:\n{exc}")
        self.update_script_state()

    def update_script_state(self):
        installed = resolve_menu_scripts_installed()
        self.script_status.setText(
            "Installed in your Resolve user scripts folder."
            if installed
            else "Not installed."
        )
        self.script_btn.setText("Remove Resolve menu scripts" if installed else "Install Resolve menu scripts")

    def toggle_export_plugin(self):
        helper = tray_helper()
        try:
            if helper.export_plugin_installed():
                helper.uninstall_export_plugin()
            else:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    helper.install_export_plugin()
                finally:
                    QApplication.restoreOverrideCursor()
        except Exception as exc:
            QMessageBox.warning(self, "DaVinci Resolve Toolkit", f"Could not update the AAC export plugin:\n{exc}")
        self.update_plugin_state()

    def update_plugin_state(self):
        installed = False
        try:
            installed = tray_helper().export_plugin_installed()
        except Exception:
            pass
        self.plugin_status.setText(
            "Installed. Restart Resolve to use it."
            if installed
            else "Not installed. Use export remux above if you are on Resolve 21 or newer."
        )
        self.plugin_btn.setText("Remove AAC export plugin" if installed else "Install AAC export plugin")

    def toggle_font_fix(self):
        helper = tray_helper()
        try:
            if helper.resolve_font_fix_installed():
                helper.uninstall_resolve_font_fix()
            else:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    helper.install_resolve_font_fix()
                finally:
                    QApplication.restoreOverrideCursor()
        except Exception as exc:
            QMessageBox.warning(self, "DaVinci Resolve Toolkit", f"Could not update the Resolve font fix:\n{exc}")
        self.update_font_state()

    def update_font_state(self):
        installed = False
        try:
            installed = tray_helper().resolve_font_fix_installed()
        except Exception:
            pass
        self.font_status.setText(
            "Installed. Resolve sees your user fonts."
            if installed
            else "Not installed."
        )
        self.font_btn.setText("Remove font fix" if installed else "Install font fix")

    def go(self, delta):
        if delta > 0 and self.index == self.stack.count() - 1:
            self.finish()
            return
        self.index = max(0, min(self.stack.count() - 1, self.index + delta))
        self.sync()

    def sync(self):
        self.stack.setCurrentIndex(self.index)
        page = self.stack.currentWidget()
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", page)
        animation.setDuration(220)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        # Drop the effect once the fade is done: a lingering QGraphicsOpacityEffect
        # caches the page and fails to repaint on hover/move, blanking the text.
        animation.finished.connect(lambda p=page: p.setGraphicsEffect(None))
        animation.start()
        self.page_animation = animation
        title, subtitle = self.titles[self.index]
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.dots.set_index(self.index)
        self.back_btn.setVisible(self.index > 0)
        self.next_btn.setText("Finish" if self.index == self.stack.count() - 1 else "Continue")

    def on_scheme_changed(self, *_args):
        app = QApplication.instance()
        if app is not None:
            apply_palette(app)
        self.setStyleSheet(self.qss())
        self.rebuild_pages()

    def rebuild_pages(self):
        index = self.index
        while self.stack.count():
            widget = self.stack.widget(0)
            self.stack.removeWidget(widget)
            widget.deleteLater()
        self.stack.addWidget(self.page_welcome())
        self.stack.addWidget(self.page_toggles())
        self.stack.addWidget(self.page_paths())
        self.stack.addWidget(self.page_export())
        self.stack.addWidget(self.page_scripts())
        self.index = min(index, self.stack.count() - 1)
        self.sync()

    def finish(self):
        self.cfg["setup_completed"] = True
        saved = save_config(self.cfg)
        self.settings_saved.emit(saved)
        self.ensure_tray_running()
        self.close()

    def ensure_tray_running(self):
        # After the setup dialog, make sure the tray is up (harmless if it already
        # is: in the integrated flow the tray launched us, so pgrep finds it).
        import subprocess
        try:
            running = subprocess.run(
                ["pgrep", "-f", "resolve_aac_tray.py"], capture_output=True
            ).returncode == 0
            if running:
                return
            tray_py = SCRIPT_DIR / "resolve_aac_tray.py"
            if tray_py.exists():
                subprocess.Popen(
                    [sys.executable, str(tray_py)],
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                )
        except Exception:
            pass

    def closeEvent(self, event):
        # Remember the size so a manual resize sticks next time.
        self.cfg["window_width"] = self.width()
        self.cfg["window_height"] = self.height()
        if not self.first_run:
            self.cfg["setup_completed"] = True
        saved = save_config(self.cfg)
        self.settings_saved.emit(saved)
        super().closeEvent(event)

    def qss(self):
        return f"""
        QWidget {{ background:{BG}; color:{TEXT}; font-family:'Inter'; }}
        QLabel {{ background:transparent; }}
        #card {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:16px; }}
        #row {{ background:transparent; border-radius:12px; }}
        #row:hover {{ background:{SURFACE2}; }}
        #sep {{ background:{BORDER}; border:none; }}
        #input {{
            background:{SURFACE2}; border:1px solid {BORDER}; border-radius:10px;
            padding:11px 14px; color:{TEXT}; font-size:14px;
        }}
        #input:focus {{ border:1px solid {ACCENT}; }}
        QPushButton#primary {{
            background:{ACCENT}; color:#fff; border:none; border-radius:11px;
            padding:12px 26px; font-size:15px; font-weight:600;
        }}
        QPushButton#primary:hover {{ background:{ACCENT_HOVER}; }}
        QPushButton#ghost {{
            background:transparent; color:{TEXT}; border:1px solid {BORDER};
            border-radius:11px; padding:12px 22px; font-size:15px; font-weight:600;
        }}
        QPushButton#ghost:hover {{ background:{SURFACE2}; border-color:{ACCENT}; }}
        """


def apply_app_font(app):
    apply_palette(app)
    icon = app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    if "Inter" in QFontDatabase.families():
        font = QFont("Inter")
    else:
        font = QFont()
    font.setPixelSize(15)
    app.setFont(font)


def main():
    app = QApplication(sys.argv)
    apply_app_font(app)
    window = SetupWindow(first_run=False)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
