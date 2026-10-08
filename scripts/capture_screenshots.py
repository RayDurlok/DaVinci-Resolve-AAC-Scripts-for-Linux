#!/usr/bin/env python3
"""Render documentation screenshots from the Qt UI using isolated example states.

Run with: python3 scripts/capture_screenshots.py
No settings, patches, launchers or network requests are changed or executed.
"""

from contextlib import ExitStack
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit

import resolve_aac_setup as setup
import resolve_aac_tray as tray
from resolve_aac_config import DEFAULT_CONFIG


def main():
    app = QApplication.instance() or QApplication([])
    setup.set_palette(setup.DARK)
    setup.apply_app_font(app)
    destination = Path(__file__).resolve().parents[1] / "docs/screenshots"
    destination.mkdir(parents=True, exist_ok=True)
    helper = SimpleNamespace(export_plugin_installed=lambda: False,
                             resolve_font_fix_installed=lambda: False)
    exists = Path.exists
    views = (
        ("01-welcome.png", "native", 0),
        ("07-native-aac.png", "native", 1),
        ("02-preferences.png", "native", 2),
        ("05-extras.png", "native", 5),
        ("03-paths.png", "legacy", 3),
        ("04-export.png", "legacy", 4),
    )
    for filename, mode, page in views:
        config = dict(DEFAULT_CONFIG, aac_mode=mode, setup_completed=True,
                      cache_dir="~/.cache/resolve-aac-remux", use_cache=True,
                      remux_exports=False, intercept_deliver_browse=False,
                      window_width=880, window_height=640)
        with ExitStack() as mocks:
            mocks.enter_context(patch.object(Path, "exists", lambda path:
                True if path == Path("/opt/resolve/bin/resolve") else exists(path)))
            mocks.enter_context(patch.object(setup, "load_config", return_value=config.copy()))
            mocks.enter_context(patch.object(setup, "save_config", side_effect=lambda cfg: cfg))
            mocks.enter_context(patch.object(setup, "check_update_async"))
            mocks.enter_context(patch.object(setup, "tray_helper", return_value=helper))
            mocks.enter_context(patch.object(setup, "resolve_menu_scripts_installed", return_value=False))
            mocks.enter_context(patch.object(tray, "autostart_enabled", return_value=False))
            mocks.enter_context(patch.object(setup.SetupWindow, "_refresh_resolve_info"))
            mocks.enter_context(patch.object(setup.SetupWindow, "native_operation"))
            window = setup.SetupWindow()
            try:
                window._apply_resolve_info(("21.1.0", "Studio"))
                window.native_state = dict(supported=True, import_active=mode == "native",
                                           export_installed=mode == "native")
                window.update_native_status()
                window.open_page(page)
                window.show()
                QTest.qWait(300)
                for widget in window.findChildren(QLabel) + window.findChildren(QLineEdit):
                    if "/home/" in widget.text():
                        raise RuntimeError("Personal path in documentation screenshot")
                if not window.grab().save(str(destination / filename)):
                    raise RuntimeError("Could not save screenshot: " + filename)
                print(filename)
            finally:
                window.close()
                app.processEvents()


if __name__ == "__main__":
    main()
