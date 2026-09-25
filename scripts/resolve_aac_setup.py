#!/usr/bin/env python3

from __future__ import annotations

import os
import json
import shutil
import sys
import threading
from pathlib import Path

try:
    from PySide6.QtCore import Property, QEasingCurve, QEvent, QProcess, QPropertyAnimation, QSize, Qt, QTimer, Signal
    from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import (
        QAbstractButton,
        QApplication,
        QButtonGroup,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QFrame,
        QGraphicsDropShadowEffect,
        QGraphicsOpacityEffect,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QPlainTextEdit,
        QProgressBar,
        QStackedWidget,
        QStyle,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    print("Resolve AAC Settings requires PySide6.", file=sys.stderr)
    print("Install it with your distro package manager, for example python3-pyside6.", file=sys.stderr)
    raise SystemExit(2)

from resolve_aac_config import APP_VERSION, NATIVE_AAC_NOTICE_VERSION, load_config, save_config
from resolve_aac_icons import info_icon


SCRIPT_DIR = Path(__file__).resolve().parent
RESOLVE_SCRIPTS_DIR = Path.home() / ".local" / "share" / "DaVinciResolve" / "Fusion" / "Scripts" / "Edit"
RESOLVE_AAC_SCRIPTS_DIR = RESOLVE_SCRIPTS_DIR / "DaVinci Resolve Toolkit"
OLD_SCRIPT_LINKS = {
    "Resolve AAC Current Clip.py": "resolve_aac_remux_current.py",
    "Resolve AAC Timeline Watch.py": "resolve_aac_timeline_watch.py",
    "Stop Resolve AAC Timeline Watch.py": "resolve_aac_timeline_watch_stop.py",
    "Resolve AAC MediaPool Watch.py": "resolve_aac_mediapool_watch.py",
    "Stop Resolve AAC MediaPool Watch.py": "resolve_aac_mediapool_watch_stop.py",
    "Restore Original Sources.py": "resolve_aac_restore.py",
    "Remux All AAC Media.py": "resolve_aac_remux_all.py",
}
SCRIPT_LINKS = {f"{Path(name).stem} (Legacy).py": target for name, target in OLD_SCRIPT_LINKS.items()}

# Two palettes; the active one is chosen from the system colour scheme at
# startup (and re-applied live if the user flips dark/light while it is open).
DARK = {
    "BG": "#0E1116", "SURFACE": "#171C23", "SURFACE2": "#1E242D", "BORDER": "#252C36",
    "TEXT": "#E7ECF3", "MUTED": "#8A94A6", "ACCENT": "#4C8BF5", "ACCENT_HOVER": "#5F99F7",
    "GOOD": "#3DD68C", "WARN": "#F0803C", "DANGER": "#FF7676", "OFF_TRACK": "#39424E",
}
LIGHT = {
    "BG": "#F5F6F8", "SURFACE": "#FFFFFF", "SURFACE2": "#EEF0F3", "BORDER": "#DCE0E6",
    "TEXT": "#1C2230", "MUTED": "#606B7A", "ACCENT": "#3B7DF0", "ACCENT_HOVER": "#2F6BD8",
    "GOOD": "#1E9E57", "WARN": "#C96A22", "DANGER": "#B42318", "OFF_TRACK": "#C6CCD6",
}

# Active palette; filled in by set_palette() (defaults to dark so importing is safe).
BG = SURFACE = SURFACE2 = BORDER = TEXT = MUTED = ACCENT = ACCENT_HOVER = GOOD = WARN = DANGER = OFF_TRACK = ""


def set_palette(palette):
    global BG, SURFACE, SURFACE2, BORDER, TEXT, MUTED, ACCENT, ACCENT_HOVER, GOOD, WARN, DANGER, OFF_TRACK
    BG, SURFACE, SURFACE2, BORDER = palette["BG"], palette["SURFACE"], palette["SURFACE2"], palette["BORDER"]
    TEXT, MUTED = palette["TEXT"], palette["MUTED"]
    ACCENT, ACCENT_HOVER = palette["ACCENT"], palette["ACCENT_HOVER"]
    GOOD, WARN, OFF_TRACK = palette["GOOD"], palette["WARN"], palette["OFF_TRACK"]
    DANGER = palette["DANGER"]


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


def migrate_legacy_menu_labels():
    for old_name, target_name in OLD_SCRIPT_LINKS.items():
        old = RESOLVE_AAC_SCRIPTS_DIR / old_name
        new = RESOLVE_AAC_SCRIPTS_DIR / f"{Path(old_name).stem} (Legacy).py"
        if not old.is_symlink() or old.resolve().name != target_name:
            continue
        if not new.exists() and not new.is_symlink():
            old.rename(new)
        elif new.is_symlink() and new.resolve() == old.resolve():
            old.unlink()


def install_resolve_menu_scripts():
    migrate_legacy_menu_labels()
    RESOLVE_AAC_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    for link_name, target_name in SCRIPT_LINKS.items():
        source = SCRIPT_DIR / target_name
        target = RESOLVE_AAC_SCRIPTS_DIR / link_name
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(source)


def remove_resolve_menu_scripts():
    for link_name in (*SCRIPT_LINKS, *OLD_SCRIPT_LINKS):
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
        self.description_label = make_label(description, 13, QFont.Normal, MUTED)
        copy.addWidget(self.description_label)
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
        self.native_process = None
        self.native_state = {}
        self._native_select_after_check = False
        self._progress_buffer = ""
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
        self.dots = StepDots(6)
        header.addWidget(self.dots, 0, Qt.AlignRight | Qt.AlignTop)
        root.addLayout(header)
        root.addSpacing(26)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.page_welcome())
        self.stack.addWidget(self.page_native())
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
            ("Native AAC", "Import and export support for Resolve Studio 21."),
            ("Preferences", "General behaviour and startup options."),
            ("Legacy paths", "Storage for the optional conversion workflow."),
            ("Legacy export", "Fallback options for other Resolve versions."),
            ("Extras", ""),
        ]
        self.index = 0
        self.sync()

    def page_welcome(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.welcome_card = Card()
        card_layout = QVBoxLayout(self.welcome_card)
        card_layout.setContentsMargins(26, 22, 26, 22)
        card_layout.setSpacing(12)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.addWidget(make_label("DaVinci Resolve Toolkit", 20, QFont.DemiBold))
        title_row.addWidget(make_label(f"v{APP_VERSION}", 13, QFont.Normal, MUTED))
        title_row.addStretch(1)
        card_layout.addLayout(title_row)
        self.welcome_intro = make_label(
            "Native AAC import and experimental export for Resolve Studio 21, "
            "with legacy conversion workflows for other versions.",
            14, QFont.Normal, MUTED)
        card_layout.addWidget(self.welcome_intro)
        resolve_ok = Path("/opt/resolve/bin/resolve").exists()

        # Studio warning, hidden while detecting; shown only when Resolve is
        # missing or turns out to be the free edition (decided by the async check).
        self.studio_warning = make_label(
            "DaVinci Resolve Studio is required. The free edition is not supported.",
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
        self.legacy_ffmpeg_row = self.check_row(
            "ffmpeg", "Used for remuxing AAC audio", shutil.which("ffmpeg") is not None)
        card_layout.addWidget(self.legacy_ffmpeg_row)

        self.welcome_update_btn = QPushButton("Update DaVinci Resolve from a ZIP in Downloads")
        self.welcome_update_btn.setObjectName("ghost")
        self.welcome_update_btn.setCursor(Qt.PointingHandCursor)
        self.welcome_update_btn.setToolTip("Update Resolve from Downloads; remove Native AAC first and reapply it afterwards if supported. Keep Resolve closed until finished.")
        self.welcome_update_btn.clicked.connect(self.update_resolve)
        card_layout.addWidget(self.welcome_update_btn, 0, Qt.AlignLeft)
        self.welcome_update_hint = make_label(
            "Before updating Resolve: close it and disable Native AAC, or use this updater "
            "to handle patch removal and reactivation automatically when supported.",
            12, QFont.Normal, DANGER)
        card_layout.addWidget(self.welcome_update_hint)
        layout.addWidget(self.welcome_card)

        # Version/edition detection scans the large Resolve binary, so keep it off
        # the UI thread and cached against the binary's mtime (see detect_resolve_info).
        if resolve_ok:
            self._refresh_resolve_info()

        self.welcome_guide_btn = QToolButton()
        self.welcome_guide_btn.setObjectName("welcomeGuide")
        self.welcome_guide_btn.setText("Quick guide")
        self.welcome_guide_btn.setCheckable(True)
        self.welcome_guide_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.welcome_guide_btn.setArrowType(Qt.RightArrow)
        self.welcome_guide_btn.setCursor(Qt.PointingHandCursor)
        self.welcome_guide_btn.setToolTip("Expand or collapse the setup and controls guide.")
        layout.addWidget(self.welcome_guide_btn, 0, Qt.AlignLeft)

        self.welcome_guide = QWidget()
        guide_layout = QVBoxLayout(self.welcome_guide)
        guide_layout.setContentsMargins(0, 0, 0, 0)
        guide_layout.setSpacing(7)
        for text in (
            "<b>Native AAC</b> · Select Native AAC on the next page. Close Resolve and approve "
            "the one-time import + export patch (experimental, Studio 21). Import normally; "
            "choose AAC-LC in Deliver for MP4 export (48 kHz stereo).",
            "<b>Legacy fallback</b> · Creates PCM copies and relinks clips; originals stay untouched. "
            "Enable automatic import watching and Local scripting in Resolve. Choose source-adjacent "
            "storage or one cache folder; optional export remux converts renders to AAC-LC.",
            "<b>Switching back</b> · Selecting Legacy removes both native components with Resolve "
            "closed and administrator approval. Native mode hides and stops Legacy tools.",
            "<b>Everyday controls</b> · Left-click the tray for Settings, right-click for Start Resolve "
            "and quick actions. Preferences includes login startup, notifications and logging. "
            "Finish saves your choices.",
            "<b>Extras</b> · KDE file dialogs, a font fix and optional Legacy remux/restore menu scripts. "
            "The ZIP installer above updates Resolve, not this toolkit.",
        ):
            guide_layout.addWidget(make_label(text, 13, QFont.Normal, MUTED))
        self.welcome_guide.hide()
        self.welcome_guide_btn.toggled.connect(self.toggle_welcome_guide)
        layout.addWidget(self.welcome_guide)

        layout.addStretch(1)
        return page

    def toggle_welcome_guide(self, expanded):
        if expanded and getattr(self, "_welcome_compact_height", None) is None:
            self._welcome_compact_height = self.height()
        self.welcome_guide.setVisible(expanded)
        self.welcome_guide_btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.fit_welcome_contents()

    def fit_welcome_contents(self):
        if not hasattr(self, "index"):
            return
        on_welcome = self.index == 0
        expanded = on_welcome and self.welcome_guide_btn.isChecked()
        # Keep the overview visible; make room for the guide instead of replacing it.
        self.welcome_guide.setVisible(expanded)
        self.layout().activate()
        needed = 560
        if on_welcome:
            page_height = self.stack.widget(0).layout().totalHeightForWidth(self.stack.width())
            needed = max(560, self.height() - self.stack.height() + page_height)
        self.setMinimumHeight(needed)
        compact_height = getattr(self, "_welcome_compact_height", None)
        if expanded:
            if compact_height is None:
                self._welcome_compact_height = self.height()
            self.resize(self.width(), max(self.height(), needed))
        elif compact_height is not None:
            self._welcome_compact_height = None
            self.resize(self.width(), max(compact_height, needed))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "index", None) == 0:
            QTimer.singleShot(0, self.fit_welcome_contents)

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
            self.fit_welcome_contents()
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

    def page_native(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        self.aac_mode_picker = QFrame()
        self.aac_mode_picker.setObjectName("nativeMode")
        modes = QHBoxLayout(self.aac_mode_picker)
        modes.setContentsMargins(3, 3, 3, 3)
        modes.setSpacing(3)
        self.aac_mode_group = QButtonGroup(self.aac_mode_picker)
        for index, title in enumerate(("Native AAC", "Legacy")):
            button = QPushButton(title)
            button.setObjectName("modeOption")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumWidth(120)
            button.setToolTip("Enable native AAC import and export; install the patch if needed." if index == 0
                              else "Remove native AAC import/export support and switch to Legacy conversions.")
            self.aac_mode_group.addButton(button, index)
            modes.addWidget(button)
        self.aac_mode_group.button(0 if self.cfg.get("aac_mode") == "native" else 1).setChecked(True)
        self.aac_mode_group.idClicked.connect(self.select_aac_mode)
        workflow = QHBoxLayout()
        workflow.addWidget(make_label("Workflow", 15, QFont.DemiBold), 1)
        workflow.addWidget(self.aac_mode_picker)
        self.workflow_info_btn = QToolButton()
        self.workflow_info_btn.setObjectName("workflowInfo")
        self.workflow_info_btn.setIcon(info_icon(MUTED, TEXT))
        self.workflow_info_btn.setIconSize(QSize(20, 20))
        self.workflow_info_btn.setFixedSize(38, 38)
        self.workflow_info_btn.setAutoRaise(True)
        self.workflow_info_btn.setCursor(Qt.PointingHandCursor)
        self.workflow_info_btn.setToolTip("Compare Native AAC and Legacy")
        self.workflow_info_btn.setAccessibleName("About AAC workflows")
        self.workflow_info_btn.clicked.connect(self.show_workflow_info)
        workflow.addWidget(self.workflow_info_btn)
        layout.addLayout(workflow)
        self.legacy_links = QWidget()
        links = QHBoxLayout(self.legacy_links)
        links.setContentsMargins(0, 0, 0, 0)
        links.setSpacing(12)
        links.addWidget(make_label("Legacy settings", 13, color=MUTED))
        for title, index in (("Import", 2), ("Cache", 3), ("Export", 4), ("Menu scripts", 5)):
            link = QToolButton()
            link.setObjectName("legacyLink")
            link.setText(title)
            link.setCursor(Qt.PointingHandCursor)
            link.clicked.connect(lambda _checked=False, page_index=index: self.open_page(page_index))
            links.addWidget(link)
        links.addStretch(1)
        layout.addWidget(self.legacy_links)
        separator = QFrame()
        separator.setObjectName("sep")
        separator.setFixedHeight(1)
        layout.addWidget(separator)
        self.legacy_comparison = make_label(
            "<b>Legacy</b><br>Converts AAC audio to PCM copies and relinks them in Resolve. "
            "Optional export post-processing converts rendered audio to AAC-LC; a separate "
            "AAC export plugin is available for Resolve 20. Compatible with more Resolve versions.<br><br>"
            "<b>Native AAC</b><br>Direct AAC import and AAC-LC export, without remux copies. "
            "Requires a one-time, experimental patch for Resolve Studio 21.<br><br>"
            "Having trouble with the native AAC patch? Try Legacy.", 14, color=MUTED)
        previous_info = getattr(self, "workflow_info", None)
        if previous_info is not None:
            previous_info.close()
            previous_info.deleteLater()
        self.workflow_info = QDialog(self)
        self.workflow_info.setWindowTitle("Native AAC and Legacy")
        self.workflow_info.resize(540, 310)
        info_layout = QVBoxLayout(self.workflow_info)
        info_layout.setContentsMargins(24, 24, 24, 24)
        info_layout.setSpacing(20)
        info_layout.addWidget(self.legacy_comparison)
        info_close = QDialogButtonBox(QDialogButtonBox.Close)
        info_close.rejected.connect(self.workflow_info.close)
        info_layout.addWidget(info_close)
        self.legacy_operation_status = make_label("", 13, color=MUTED)
        self.legacy_operation_status.hide()
        layout.addWidget(self.legacy_operation_status)
        self.native_info = QWidget()
        native_layout = QVBoxLayout(self.native_info)
        native_layout.setContentsMargins(0, 0, 0, 0)
        native_layout.setSpacing(16)
        status = QHBoxLayout()
        self.native_status_label = make_label("Checking installation...", 19, QFont.DemiBold)
        status.addWidget(self.native_status_label, 1)
        self.native_check_btn = QToolButton()
        self.native_check_btn.setObjectName("nativeRefresh")
        self.native_check_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.native_check_btn.setFixedSize(34, 34)
        self.native_check_btn.setToolTip("Refresh installation status")
        self.native_check_btn.setAccessibleName("Refresh installation status")
        self.native_check_btn.clicked.connect(lambda: self.native_operation("status"))
        native_layout.addLayout(status)
        self.native_summary = make_label("", 14, color=MUTED)
        native_layout.addWidget(self.native_summary)
        actions = QHBoxLayout()
        self.native_install_btn = QPushButton("Enable native AAC")
        self.native_install_btn.setObjectName("primary")
        self.native_install_btn.setToolTip("Install the import patch and export plugin together.")
        self.native_install_btn.clicked.connect(lambda: self.native_operation("install"))
        self.native_remove_btn = QPushButton("Disable native AAC")
        self.native_remove_btn.setObjectName("ghost")
        self.native_remove_btn.setToolTip("Disable both import and export support and restore Resolve's original files.")
        self.native_remove_btn.clicked.connect(lambda: self.native_operation("uninstall"))
        for button in (self.native_install_btn, self.native_remove_btn):
            button.setMinimumHeight(42)
            button.setCursor(Qt.PointingHandCursor)
            actions.addWidget(button)
        actions.addStretch(1)
        native_layout.addLayout(actions)
        native_layout.addWidget(make_label("Experimental. Close Resolve before making changes. Original files are backed up.",
                                           12, color=MUTED))
        layout.addWidget(self.native_info)
        self.native_progress = QWidget()
        progress_layout = QVBoxLayout(self.native_progress)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(4)
        self.progress_title = make_label("Activating Native AAC", 18, QFont.DemiBold)
        progress_layout.addWidget(self.progress_title)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("nativeProgress")
        self.progress_bar.setFixedHeight(22)
        self.progress_bar.setFormat("%v / %m steps complete")
        progress_layout.addWidget(self.progress_bar)
        self.progress_steps_widget = QWidget()
        self.progress_steps_layout = QVBoxLayout(self.progress_steps_widget)
        self.progress_steps_layout.setContentsMargins(0, 0, 0, 0)
        self.progress_steps_layout.setSpacing(2)
        progress_layout.addWidget(self.progress_steps_widget)
        self.progress_message = make_label("", 13, color=MUTED)
        progress_layout.addWidget(self.progress_message)
        self.progress_done_btn = QToolButton()
        self.progress_done_btn.setObjectName("nativeDetails")
        self.progress_done_btn.setText("Done")
        self.progress_done_btn.clicked.connect(self.dismiss_native_progress)
        self.progress_done_btn.hide()
        self.progress_rows = {}
        self.progress_states = {}
        self.native_progress.hide()
        layout.addWidget(self.native_progress)
        self.native_details_btn = QToolButton()
        self.native_details_btn.setObjectName("nativeDetails")
        self.native_details_btn.setText("Details and credits")
        self.native_details_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.native_details_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.native_details_btn.setToolTip("Open installation logs and third-party credits")
        utilities = QHBoxLayout()
        utilities.addWidget(self.native_details_btn, 0, Qt.AlignLeft)
        utilities.addStretch(1)
        utilities.addWidget(self.progress_done_btn)
        utilities.addWidget(self.native_check_btn)
        layout.addLayout(utilities)
        previous_details = getattr(self, "native_details", None)
        if previous_details is not None:
            previous_details.close()
            previous_details.deleteLater()
        self.native_details = QDialog(self)
        self.native_details.setWindowTitle("Native AAC - Details and credits")
        self.native_details.resize(720, 420)
        self.native_details.setMinimumSize(560, 320)
        details = QVBoxLayout(self.native_details)
        details.setContentsMargins(20, 20, 20, 20)
        details.setSpacing(16)
        self.native_log = QPlainTextEdit()
        self.native_log.setObjectName("nativeLog")
        self.native_log.setReadOnly(True)
        self.native_log.setMaximumBlockCount(250)
        details.addWidget(self.native_log, 1)
        credits = make_label(
            f'Import: <a style="color:{ACCENT}" href="https://github.com/josephg/resolve-aacfix">'
            'Seph Gentle / resolve-aacfix</a> (MIT).<br>'
            f'Export: based on <a style="color:{ACCENT}" href="https://github.com/Toxblh/davinci-linux-aac-codec">'
            "Toxblh's AAC encoder</a> (GPLv3).", 12, color=MUTED)
        credits.setOpenExternalLinks(True)
        details.addWidget(credits)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.native_details.close)
        details.addWidget(close)
        self.native_details_btn.clicked.connect(self.show_native_details)
        layout.addStretch(1)
        self.native_install_btn.hide()
        self.native_remove_btn.hide()
        QTimer.singleShot(0, lambda: self.native_operation("status"))
        return page

    def show_native_details(self):
        self.native_details.show()
        self.native_details.raise_()
        self.native_details.activateWindow()

    def show_workflow_info(self):
        self.workflow_info.show()
        self.workflow_info.raise_()
        self.workflow_info.activateWindow()

    def begin_native_progress(self, action):
        steps = {
            "install": [("check", "Check compatibility"), ("download", "Prepare verified downloads"),
                        ("build", "Build export plugin"), ("import", "Apply import patch"),
                        ("export", "Install export plugin"), ("verify", "Verify import and export")],
            "uninstall": [("check", "Check Resolve is closed"), ("download", "Prepare restore tools"),
                          ("restore", "Restore import and export"), ("verify", "Verify removal")],
            "install-deps": [("dependencies", "Install required build tools")],
        }[action]
        while self.progress_steps_layout.count():
            self.progress_steps_layout.takeAt(0).widget().deleteLater()
        self.progress_rows = {}
        self.progress_states = {key: "pending" for key, _ in steps}
        self._progress_current = steps[0][0]
        self._progress_action = action
        for key, title in steps:
            row = QWidget()
            row.setFixedHeight(22)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            icon = QLabel()
            icon.setFixedSize(18, 18)
            label = make_label(title, 13)
            state = make_label("Pending", 12, color=MUTED)
            row_layout.addWidget(icon)
            row_layout.addWidget(label, 1)
            row_layout.addWidget(state)
            self.progress_steps_layout.addWidget(row)
            self.progress_rows[key] = (icon, state)
        self.progress_title.setText({"install": "Activating Native AAC", "uninstall": "Switching to Legacy",
                                     "install-deps": "Installing build tools"}[action])
        self.progress_bar.setRange(0, len(steps))
        self.progress_bar.setValue(0)
        self.progress_message.setText("Preparing...")
        self.progress_done_btn.hide()
        self.native_progress.show()
        self.sync()

    def apply_progress_event(self, event):
        if not isinstance(event, dict):
            return
        step, state = event.get("step"), event.get("state")
        if step not in self.progress_rows or state not in ("running", "waiting", "done", "failed"):
            return
        self._progress_current = step
        self.progress_states[step] = state
        icon, label = self.progress_rows[step]
        symbols = {"running": QStyle.SP_BrowserReload, "waiting": QStyle.SP_MessageBoxInformation,
                   "done": QStyle.SP_DialogApplyButton, "failed": QStyle.SP_MessageBoxCritical}
        icon.setPixmap(self.style().standardIcon(symbols[state]).pixmap(16, 16))
        label.setText({"running": "Working", "waiting": "Approval needed", "done": "Done", "failed": "Failed"}[state])
        color = GOOD if state == "done" else WARN if state in ("waiting", "failed") else ACCENT
        label.setStyleSheet(f"color:{color};")
        self.progress_bar.setValue(sum(value == "done" for value in self.progress_states.values()))
        if isinstance(event.get("message"), str) and event["message"]:
            self.progress_message.setText(event["message"])

    def consume_progress_output(self, text):
        self._progress_buffer += text
        while "\n" in self._progress_buffer:
            line, self._progress_buffer = self._progress_buffer.split("\n", 1)
            if not line.startswith("NATIVE_AAC_PROGRESS "):
                continue
            try:
                event = json.loads(line[len("NATIVE_AAC_PROGRESS "):])
            except ValueError:
                continue
            if (isinstance(event, dict) and event.get("step") == "verify" and
                    event.get("state") == "done" and getattr(self, "_native_action", None) == "install"):
                event.update(state="running", message="Confirming activation before switching workflows.")
            self.apply_progress_event(event)

    def finish_native_progress(self, successful):
        if not self.progress_rows:
            return
        if successful:
            for step in self.progress_states:
                self.apply_progress_event({"step": step, "state": "done"})
            self.progress_title.setText({"install": "Native AAC activated", "uninstall": "Legacy restored",
                                        "install-deps": "Build tools installed"}[self._progress_action])
            self.progress_message.setText("Ready. You can start Resolve." if self._progress_action != "install-deps"
                                          else "Select Native AAC again to continue setup.")
        else:
            self.apply_progress_event({"step": self._progress_current, "state": "failed"})
            self.progress_title.setText("Could not complete changes")
            self.progress_message.setText("Your workflow is unchanged. See details for the error.")
        self.progress_done_btn.show()

    def dismiss_native_progress(self):
        self.native_progress.hide()
        self.progress_done_btn.hide()
        self.sync()

    def update_native_status(self):
        state = self.native_state
        supported = state.get("supported", False)
        complete = state.get("import_active") and state.get("export_installed")
        partial = bool(state.get("import_active") or state.get("export_installed"))
        self.aac_mode_group.button(0).setEnabled(bool(supported))
        self.native_install_btn.setVisible(self.cfg.get("aac_mode") == "native" and not complete and supported)
        self.native_install_btn.setEnabled(supported)
        self.native_install_btn.setText("Repair native AAC" if partial else "Enable native AAC")
        self.native_remove_btn.setVisible(partial)
        if not supported:
            title, summary = "Not supported", "Requires Resolve Studio 21 on Linux x86-64. Legacy conversions remain available."
        elif complete:
            title = "Native AAC installed"
            summary = "Import patch active. AAC-LC export plugin installed."
        elif partial:
            title, summary = "Installation incomplete", "Repair or remove both native AAC components."
        else:
            title, summary = "Native AAC not installed", "Import patch and AAC-LC export plugin."
        if state.get("update_message") and not complete:
            summary += " Resolve update needs attention; see Details and credits."
        self.native_status_label.setText(title)
        self.native_summary.setText(summary)

    def select_aac_mode(self, index):
        mode = "native" if index == 0 else "legacy"
        if mode == "legacy" and (self.cfg.get("aac_mode") == "native" or
                                 self.native_state.get("import_active") or self.native_state.get("export_installed")):
            # The selection stays Native until the privileged rollback succeeds.
            self.aac_mode_group.button(0 if self.cfg.get("aac_mode") == "native" else 1).setChecked(True)
            self.native_operation("uninstall")
            return
        if mode == "native" and not (self.native_state.get("supported") and self.native_state.get("import_active") and self.native_state.get("export_installed")):
            self.aac_mode_group.button(0 if self.cfg.get("aac_mode") == "native" else 1).setChecked(True)
            if self.native_state.get("supported"):
                self.native_operation("install")
            else:
                QMessageBox.warning(self, "Native AAC", "Native AAC requires Resolve Studio 21 on Linux x86-64.")
            return
        self.commit_aac_mode(mode)

    def commit_aac_mode(self, mode):
        self.aac_mode_group.button(0 if mode == "native" else 1).setChecked(True)
        self.cfg["aac_mode"] = mode
        self.update_native_status()
        self.settings_saved.emit(save_config(self.cfg))
        self.sync()

    def native_operation(self, action):
        if self.native_process is not None and self.native_process.state() != QProcess.NotRunning:
            return
        if action in ("install", "uninstall"):
            from resolve_aac_native import resolve_processes
            if resolve_processes():
                QMessageBox.information(self, "Close Resolve first",
                                        "Close DaVinci Resolve before changing its AAC patch. "
                                        "Your current workflow remains selected until the change succeeds.")
                return
        if action == "install" and self.native_state.get("missing_tools"):
            missing = ", ".join(self.native_state["missing_tools"])
            if not self.native_state.get("can_install_dependencies"):
                QMessageBox.warning(self, "Native AAC", "Missing build dependencies: " + missing + ". Install these with your package manager first.")
                return
            if QMessageBox.question(self, "Native AAC dependencies",
                                    "Missing: " + missing + ". Install the C/C++ build tools using your system package manager?",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
            action = "install-deps"
        if action not in ("status", "install-deps"):
            message = (
                "Download the pinned, checksum-verified resolve-aacfix release and build the experimental "
                "AAC export plugin locally? This modifies /opt/resolve, keeps upstream backups and requires "
                "administrator approval. Close Resolve and back up your projects first. "
                "Use is subject to Resolve's terms and applicable codec licensing."
                if action == "install" else
                "Switch to Legacy? This removes both the native import patch and export plugin, "
                "restores Resolve and FFmpeg from verified backups, and re-enables your saved "
                "Legacy settings after successful removal. Administrator approval is required."
            )
            if QMessageBox.question(self, "Native AAC", message,
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        if action != "status" or self.native_progress.isHidden():
            self.native_log.clear()
        self._native_output = ""
        self._native_action = action
        self._progress_buffer = ""
        if action != "status":
            self.begin_native_progress(action)
        self.native_status_label.setText("Checking installation..." if action == "status" else "Applying changes...")
        self.native_summary.setText("" if action == "status" else "Administrator approval may be required.")
        self.legacy_operation_status.setText("Applying changes; administrator approval may be required.")
        self.legacy_operation_status.hide()
        for button in (self.native_install_btn, self.native_remove_btn, self.native_check_btn, self.aac_mode_picker):
            button.setEnabled(False)
        if self.native_process is not None:
            self.native_process.deleteLater()
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(self.read_native_output)
        process.finished.connect(self.native_finished)
        process.errorOccurred.connect(self.native_process_error)
        self.native_process = process
        process.start(sys.executable, [str(SCRIPT_DIR / "resolve_aac_native.py"), action])

    def read_native_output(self):
        text = bytes(self.native_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._native_output += text
        self.consume_progress_output(text)
        if self._native_action != "status":
            self.native_log.insertPlainText(text)
            self.native_log.verticalScrollBar().setValue(self.native_log.verticalScrollBar().maximum())

    def native_process_error(self, error):
        if error == QProcess.FailedToStart:
            self._native_output = self.native_process.errorString()
            self.native_log.appendPlainText(self._native_output)
            self.native_finished(1, QProcess.CrashExit)

    def native_finished(self, code, _status):
        self.read_native_output()
        action = self._native_action
        for button in (self.native_install_btn, self.native_remove_btn, self.native_check_btn, self.aac_mode_picker):
            button.setEnabled(True)
        if code != 0:
            self.finish_native_progress(False)
            self._native_select_after_check = False
            self.native_state = {}
            self.aac_mode_picker.setEnabled(False)
            self.native_status_label.setText("Changes could not be completed")
            self.native_summary.setText("Check the details, then refresh the installation status.")
            self.legacy_operation_status.setText("Changes could not be completed. Your workflow is unchanged.")
            self.legacy_operation_status.setVisible(self.cfg.get("aac_mode") != "native" and self.native_progress.isHidden())
            self.show_native_details()
            return
        if action == "status":
            try:
                self.native_state = json.loads(self._native_output)
            except ValueError:
                self.finish_native_progress(False)
                self.native_state = {}
                self.aac_mode_picker.setEnabled(False)
                self._native_select_after_check = False
                self.native_status_label.setText("Could not read native AAC status.")
                self.legacy_operation_status.setText("Could not read native AAC status. Refresh to try again.")
                self.legacy_operation_status.setVisible(self.cfg.get("aac_mode") != "native" and self.native_progress.isHidden())
                self.show_native_details()
                return
            state = self.native_state
            if self.native_progress.isHidden():
                self.native_log.setPlainText(state.get("details", ""))
            else:
                self.native_log.appendPlainText("\nVerification:\n" + state.get("details", ""))
            supported = state.get("supported", False)
            self.update_native_status()
            if self._native_select_after_check and supported and state.get("import_active") and state.get("export_installed"):
                self._native_select_after_check = False
                self.select_aac_mode(0)
                self.finish_native_progress(True)
            elif self._native_select_after_check:
                self._native_select_after_check = False
                self.finish_native_progress(False)
                self.progress_message.setText("Final verification failed. Native mode was not selected; inspect the details.")
        else:
            if action == "uninstall":
                self.native_state.update(import_active=False, export_installed=False)
                self.update_native_status()
                self.commit_aac_mode("legacy")
            if action in ("uninstall", "install-deps"):
                self.finish_native_progress(True)
            self._native_select_after_check = action == "install"
            QTimer.singleShot(0, lambda: self.native_operation("status"))

    def page_toggles(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        card = Card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(6, 6, 6, 6)
        card_layout.setSpacing(0)

        self.legacy_import_row = self._config_toggle_row(
            "watch_manual_resolve", "Legacy: auto-remux AAC on import",
            "Active only in Legacy mode, including Resolve opened from its normal launcher.")
        rows = [self.legacy_import_row]

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
                if index == 0:
                    self.legacy_import_separator = sep

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
        remux_layout.addWidget(make_label("Legacy export remux", 18, QFont.DemiBold))
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
            "Runs after renders in Legacy mode; video is copied, not re-rendered.",
            remux_toggle,
        ))
        layout.addWidget(remux_card)

        # 2) AAC export plugin, the alternative, Resolve 20 only.
        plugin_card = Card()
        plugin_layout = QVBoxLayout(plugin_card)
        plugin_layout.setContentsMargins(24, 22, 24, 22)
        plugin_layout.setSpacing(12)
        plugin_layout.addWidget(make_label("Legacy AAC plugin (Resolve 20 only)", 18, QFont.DemiBold))
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
        self.kde_dialog_row = self._config_toggle_row(
            "intercept_deliver_browse", "Native KDE file dialogs",
            "Native file pickers and Deliver destination. Relink stays in Resolve.")
        layout.addWidget(self.kde_dialog_row)

        self.font_btn = QPushButton()
        self.font_btn.setObjectName("ghost")
        self.font_btn.setCursor(Qt.PointingHandCursor)
        self.font_btn.setToolTip("Make Resolve and Fusion scan user-installed fonts.")
        self.font_btn.clicked.connect(self.toggle_font_fix)
        font_row = SettingRow("Resolve font fix", "", self.font_btn)
        self.font_status = font_row.description_label
        self.update_font_state()
        layout.addWidget(font_row)

        self.script_btn = QPushButton()
        self.script_btn.setObjectName("ghost")
        self.script_btn.setCursor(Qt.PointingHandCursor)
        self.script_btn.setToolTip("Add remux, restore and watcher commands under Workspace > Scripts in Resolve.")
        self.script_btn.clicked.connect(self.toggle_resolve_menu_scripts)
        self.legacy_scripts_card = SettingRow("Resolve menu scripts (Legacy)", "", self.script_btn)
        self.script_status = self.legacy_scripts_card.description_label
        self.update_script_state()
        layout.addWidget(self.legacy_scripts_card)

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
            else "Not installed. For Studio 21 use Native AAC, or the Legacy export remux fallback."
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

    def visible_pages(self):
        return [0, 1, 2, 5] if self.cfg.get("aac_mode") == "native" else list(range(self.stack.count()))

    def open_page(self, index):
        if index in self.visible_pages():
            self.index = index
            self.sync()

    def go(self, delta):
        pages = self.visible_pages()
        position = pages.index(self.index) if self.index in pages else 1
        if delta > 0 and position == len(pages) - 1:
            self.finish()
            return
        self.index = pages[max(0, min(len(pages) - 1, position + delta))]
        self.sync()

    def sync(self):
        legacy = self.cfg.get("aac_mode") != "native"
        progressing = not self.native_progress.isHidden()
        self.native_info.setVisible(not legacy and not progressing)
        if not legacy:
            self.legacy_operation_status.hide()
        for widget in (self.legacy_ffmpeg_row, self.legacy_import_row,
                       self.legacy_import_separator, self.legacy_scripts_card):
            widget.setVisible(legacy)
        self.legacy_links.setVisible(legacy and not progressing)
        pages = self.visible_pages()
        if self.index not in pages:
            self.index = 1
        page_changed = self.stack.currentIndex() != self.index
        if page_changed:
            previous_animation = getattr(self, "page_animation", None)
            if previous_animation is not None:
                previous_animation.stop()
            self.stack.currentWidget().setGraphicsEffect(None)
            self.stack.setCurrentIndex(self.index)
            page = self.stack.currentWidget()
            effect = QGraphicsOpacityEffect(page)
            page.setGraphicsEffect(effect)
            animation = QPropertyAnimation(effect, b"opacity", page)
            animation.setDuration(220)
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            animation.finished.connect(lambda p=page: p.setGraphicsEffect(None))
            animation.start()
            self.page_animation = animation
        title, subtitle = self.titles[self.index]
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.dots.count = len(pages)
        self.dots.set_index(pages.index(self.index))
        self.back_btn.setVisible(self.index > 0)
        self.next_btn.setText("Finish" if self.index == self.stack.count() - 1 else "Continue")
        self.fit_welcome_contents()

    def on_scheme_changed(self, *_args):
        app = QApplication.instance()
        if app is not None:
            apply_palette(app)
        self.setStyleSheet(self.qss())
        self.rebuild_pages()

    def rebuild_pages(self):
        guide_expanded = self.welcome_guide_btn.isChecked()
        progress = None
        if not self.native_progress.isHidden():
            progress = (self._progress_action, dict(self.progress_states), self._progress_current,
                        self.progress_title.text(), self.progress_message.text(), not self.progress_done_btn.isHidden())
        animation = getattr(self, "page_animation", None)
        if animation is not None:
            animation.stop()
            self.page_animation = None
        index = self.index
        while self.stack.count():
            widget = self.stack.widget(0)
            self.stack.removeWidget(widget)
            widget.deleteLater()
        self.stack.addWidget(self.page_welcome())
        self.stack.addWidget(self.page_native())
        self.stack.addWidget(self.page_toggles())
        self.stack.addWidget(self.page_paths())
        self.stack.addWidget(self.page_export())
        self.stack.addWidget(self.page_scripts())
        self.welcome_guide_btn.setChecked(guide_expanded)
        self.index = min(index, self.stack.count() - 1)
        self.sync()
        if progress is not None:
            action, states, current, title, message, finished = progress
            self.begin_native_progress(action)
            for step, state in states.items():
                if state != "pending":
                    self.apply_progress_event({"step": step, "state": state})
            self._progress_current = current
            self.progress_title.setText(title)
            self.progress_message.setText(message)
            self.progress_done_btn.setVisible(finished)

    def finish(self):
        self.cfg["setup_completed"] = True
        self.cfg["native_aac_notice_version"] = NATIVE_AAC_NOTICE_VERSION
        saved = save_config(self.cfg)
        self.settings_saved.emit(saved)
        self.close()

    def closeEvent(self, event):
        if self.native_process is not None and self.native_process.state() != QProcess.NotRunning:
            QMessageBox.information(self, "Native AAC", "Please wait for the native AAC operation to finish.")
            event.ignore()
            return
        # Remember the size so a manual resize sticks next time.
        self.cfg["window_width"] = self.width()
        self.cfg["window_height"] = getattr(self, "_welcome_compact_height", None) or self.height()
        if not self.first_run:
            if not self.cfg.get("setup_completed"):
                self.cfg["native_aac_notice_version"] = NATIVE_AAC_NOTICE_VERSION
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
        QFrame#nativeMode {{
            background:{SURFACE}; border:1px solid {BORDER}; border-radius:8px;
        }}
        QPushButton#modeOption {{
            background:transparent; color:{MUTED}; border:1px solid transparent;
            border-radius:5px; padding:8px 14px; font-size:14px;
        }}
        QPushButton#modeOption:hover {{ background:{SURFACE2}; color:{TEXT}; }}
        QPushButton#modeOption:checked {{ background:{ACCENT}; color:#fff; }}
        QPushButton#modeOption:focus {{ border-color:{TEXT}; }}
        QPushButton#modeOption:disabled {{ color:{MUTED}; background:{SURFACE2}; }}
        QToolButton#nativeRefresh, QToolButton#nativeDetails {{
            background:transparent; border:none; border-radius:4px;
            color:{MUTED}; padding:4px; font-size:13px;
        }}
        QToolButton#nativeRefresh:hover, QToolButton#nativeDetails:hover {{
            background:{SURFACE2}; color:{TEXT};
        }}
        QToolButton#welcomeGuide {{
            background:transparent; border:1px solid transparent; border-radius:4px;
            color:{TEXT}; padding:6px 4px; font-size:14px; font-weight:600;
        }}
        QToolButton#welcomeGuide:hover {{ background:{SURFACE2}; }}
        QToolButton#welcomeGuide:focus {{ border-color:{ACCENT}; }}
        QToolButton#workflowInfo {{
            background:transparent; border:1px solid transparent; border-radius:8px; padding:0;
        }}
        QToolButton#workflowInfo:hover {{ background:{SURFACE2}; border-color:{BORDER}; }}
        QToolButton#workflowInfo:pressed {{ background:{SURFACE}; border-color:{MUTED}; }}
        QToolButton#workflowInfo:focus {{ border-color:{ACCENT}; }}
        QToolButton#legacyLink {{
            background:transparent; border:none; border-radius:4px;
            color:{ACCENT}; padding:6px 8px; font-size:13px;
        }}
        QToolButton#legacyLink:hover {{ background:{SURFACE2}; }}
        QPlainTextEdit#nativeLog {{
            background:{SURFACE}; border:1px solid {BORDER}; border-radius:6px;
            padding:8px; font-family:monospace; font-size:12px; color:{MUTED};
        }}
        QProgressBar#nativeProgress {{
            background:{SURFACE2}; border:none; border-radius:4px;
            color:{TEXT}; text-align:center; font-size:12px;
        }}
        QProgressBar#nativeProgress::chunk {{ background:{ACCENT}; border-radius:4px; }}
        QPushButton#primary:disabled,
        QPushButton#ghost:disabled {{ color:{MUTED}; background:{SURFACE2}; }}
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
    from resolve_aac_tray import main as tray_main
    return tray_main(["--settings", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
