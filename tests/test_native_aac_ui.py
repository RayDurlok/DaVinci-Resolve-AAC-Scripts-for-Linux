import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from PySide6.QtWidgets import QApplication, QScrollArea
import resolve_aac_setup as setup
import resolve_aac_native as native
from resolve_aac_config import DEFAULT_CONFIG

NATIVE_OPERATION = setup.SetupWindow.native_operation


class NativePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        for target, kwargs in (
            ("load_config", {"return_value": dict(DEFAULT_CONFIG)}),
            ("save_config", {"side_effect": lambda cfg: cfg}),
            ("SetupWindow._refresh_resolve_info", {}),
            ("SetupWindow.native_operation", {}),
        ):
            mock = patch.object(setup, target, **kwargs) if "." not in target else patch(
                "resolve_aac_setup." + target, **kwargs)
            mock.start()
            self.addCleanup(mock.stop)
        self.window = setup.SetupWindow(first_run=True)
        self.window.index = 1
        self.window.sync()
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.window.close)

    def state(self, imported=False, exported=False, supported=True):
        self.window.native_state = dict(supported=supported, import_active=imported,
                                        export_installed=exported)
        self.window.update_native_status()
        self.app.processEvents()

    def finish_removal(self, code=0):
        self.window._native_action = "uninstall"
        with patch.object(self.window, "read_native_output"), patch.object(setup.QTimer, "singleShot"):
            self.window.native_finished(code, setup.QProcess.NormalExit)
        self.app.processEvents()

    def test_welcome_guide_starts_collapsed_and_toggles_with_keyboard(self):
        from PySide6.QtTest import QTest
        self.window.open_page(0)
        self.window.native_operation.reset_mock()
        button = self.window.welcome_guide_btn
        self.assertFalse(button.isChecked())
        self.assertTrue(self.window.welcome_guide.isHidden())
        self.assertEqual(button.arrowType(), setup.Qt.RightArrow)
        button.setFocus()
        QTest.keyClick(button, setup.Qt.Key_Space)
        self.assertTrue(self.window.welcome_guide.isVisible())
        self.assertTrue(self.window.welcome_intro.isVisible())
        self.assertTrue(self.window.welcome_card.isVisible())
        self.assertTrue(self.window.welcome_update_btn.isVisible())
        self.assertEqual(button.arrowType(), setup.Qt.DownArrow)
        QTest.keyClick(button, setup.Qt.Key_Space)
        self.assertTrue(self.window.welcome_guide.isHidden())
        self.assertTrue(self.window.welcome_intro.isVisible())
        self.window.native_operation.assert_not_called()

    def test_welcome_guide_survives_navigation_and_theme_rebuild(self):
        self.window.open_page(0)
        self.window.welcome_guide_btn.click()
        self.window.open_page(1)
        self.window.open_page(0)
        self.assertTrue(self.window.welcome_guide.isVisible())
        self.window.rebuild_pages()
        self.assertTrue(self.window.welcome_guide_btn.isChecked())
        self.assertFalse(self.window.welcome_guide.isHidden())
        self.assertTrue(self.window.welcome_intro.isVisible())

    def test_welcome_guide_fits_minimum_window_in_both_modes(self):
        from PySide6.QtWidgets import QLabel
        self.window.open_page(0)
        self.window.resize(760, 560)
        self.window.welcome_guide_btn.click()
        for mode in ("native", "legacy"):
            for warning in (False, True):
                with self.subTest(mode=mode, warning=warning):
                    self.window.cfg["aac_mode"] = mode
                    self.window.sync()
                    self.window.studio_warning.setVisible(warning)
                    self.app.processEvents()
                    self.window.fit_welcome_contents()
                    self.app.processEvents()
                    self.assertEqual(self.window.width(), 760)
                    page = self.window.stack.widget(0)
                    self.assertEqual(page.findChildren(QScrollArea), [])
                    self.assertTrue(page.rect().contains(self.window.welcome_card.geometry()))
                    self.assertTrue(page.rect().contains(self.window.welcome_guide.geometry()))
                    self.assertLess(self.window.welcome_card.geometry().bottom(),
                                    self.window.welcome_guide_btn.geometry().top())
                    self.assertLess(self.window.welcome_guide_btn.geometry().bottom(),
                                    self.window.welcome_guide.geometry().top())
                    previous_bottom = -1
                    for label in self.window.welcome_guide.findChildren(QLabel):
                        self.assertGreater(label.y(), previous_bottom)
                        self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
                        self.assertTrue(self.window.welcome_guide.rect().contains(label.geometry()))
                        previous_bottom = label.geometry().bottom()

    def test_welcome_expansion_restores_window_height_after_collapse_or_navigation(self):
        self.window.open_page(0)
        self.window.resize(880, 600)
        self.app.processEvents()
        height = self.window.height()
        self.window.welcome_guide_btn.click()
        self.app.processEvents()
        self.assertGreater(self.window.height(), height)
        self.window.welcome_guide_btn.click()
        self.app.processEvents()
        self.assertEqual(self.window.height(), height)
        self.window.welcome_guide_btn.click()
        self.window.open_page(1)
        self.app.processEvents()
        self.assertEqual(self.window.height(), height)
        self.window.open_page(0)
        self.app.processEvents()
        self.assertTrue(self.window.welcome_guide.isVisible())
        self.assertTrue(self.window.welcome_card.isVisible())

    def test_welcome_keeps_original_status_rows_and_update_action(self):
        from PySide6.QtWidgets import QLabel
        self.window.open_page(0)
        labels = [label.text() for label in self.window.welcome_card.findChildren(QLabel)]
        for text in ("DaVinci Resolve Toolkit", "DaVinci Resolve", "ffmpeg", "Used for remuxing AAC audio"):
            self.assertIn(text, labels)
        self.assertFalse(self.window.welcome_guide_btn.isChecked())
        self.assertTrue(self.window.welcome_update_hint.isVisible())
        self.assertIn("disable Native AAC", self.window.welcome_update_hint.text())
        self.assertIn(setup.DANGER, self.window.welcome_update_hint.styleSheet())
        with patch.object(setup, "tray_helper") as helper:
            self.window.welcome_update_btn.click()
            helper.return_value.launch_resolve_updater.assert_called_once()

    def test_details_open_separately_without_resizing_page(self):
        self.state()
        self.assertFalse(self.window.native_details.isVisible())
        self.assertFalse(self.window.native_install_btn.isVisible())
        self.assertFalse(self.window.native_remove_btn.isVisible())
        size = self.window.stack.widget(1).size()
        self.window.native_details_btn.click()
        self.assertTrue(self.window.native_details.isVisible())
        self.assertTrue(self.window.native_details.isWindow())
        self.assertEqual(size, self.window.stack.widget(1).size())
        self.window.native_details.close()
        self.assertFalse(self.window.native_details.isVisible())

    def test_complete_installation_has_one_paired_removal_action(self):
        self.window.cfg["aac_mode"] = "native"
        self.window.sync()
        self.state(True, True)
        self.assertFalse(self.window.native_install_btn.isVisible())
        self.assertTrue(self.window.native_remove_btn.isVisible())
        self.window.native_remove_btn.click()
        self.window.native_operation.assert_called_with("uninstall")

    def test_partial_installation_offers_repair_and_removal(self):
        self.window.cfg["aac_mode"] = "native"
        self.window.sync()
        self.state(True, False)
        self.assertEqual(self.window.native_install_btn.text(), "Repair native AAC")
        self.assertTrue(self.window.native_remove_btn.isVisible())
        self.window.native_install_btn.click()
        self.window.native_operation.assert_called_with("install")

    def test_unsupported_installation_can_still_be_removed(self):
        self.window.cfg["aac_mode"] = "native"
        self.window.sync()
        self.state(True, True, supported=False)
        self.assertFalse(self.window.native_install_btn.isVisible())
        self.assertTrue(self.window.native_remove_btn.isVisible())

    def test_page_fits_minimum_window_without_scroll_area(self):
        self.state(True, True)
        self.window.resize(760, 560)
        self.app.processEvents()
        page = self.window.stack.widget(1)
        self.assertEqual(page.findChildren(QScrollArea), [])
        self.assertLessEqual(page.minimumSizeHint().height(), page.height())
        self.assertLessEqual(page.minimumSizeHint().width(), page.width())

    def test_segments_select_only_verified_native_and_keep_legacy_settings(self):
        self.state()
        self.assertTrue(self.window.aac_mode_group.button(0).isEnabled())
        self.window.aac_mode_group.button(0).click()
        self.window.native_operation.assert_called_with("install")
        self.assertEqual(self.window.cfg["aac_mode"], "legacy")
        self.assertEqual(self.window.aac_mode_group.checkedId(), 1)
        self.state(True, True)
        self.window.aac_mode_group.button(0).click()
        self.assertEqual(self.window.cfg["aac_mode"], "native")
        self.assertEqual(self.window.aac_mode_group.checkedId(), 0)
        self.window.aac_mode_group.button(1).click()
        self.window.native_operation.assert_called_with("uninstall")
        self.assertEqual(self.window.cfg["aac_mode"], "native")
        self.assertEqual(self.window.aac_mode_group.checkedId(), 0)
        self.finish_removal()
        self.assertEqual(self.window.cfg["aac_mode"], "legacy")
        self.assertEqual(self.window.aac_mode_group.checkedId(), 1)
        self.assertFalse(self.window.native_state["import_active"])
        self.assertFalse(self.window.native_state["export_installed"])

    def test_fresh_setup_acknowledges_architecture(self):
        self.window.finish()
        self.assertEqual(self.window.cfg["native_aac_notice_version"], setup.NATIVE_AAC_NOTICE_VERSION)

    def test_native_mode_hides_legacy_pages_and_controls_reversibly(self):
        self.state(True, True)
        saved_options = {key: self.window.cfg[key] for key in ("use_cache", "cache_dir", "remux_exports", "watch_manual_resolve")}
        self.window.select_aac_mode(0)
        self.assertEqual(self.window.visible_pages(), [0, 1, 2, 5])
        self.assertEqual(self.window.dots.count, 4)
        for widget in (self.window.legacy_import_row, self.window.legacy_import_separator,
                       self.window.legacy_scripts_card, self.window.legacy_ffmpeg_row):
            self.assertTrue(widget.isHidden())
        self.window.go(1)
        self.assertEqual(self.window.index, 2)
        self.window.go(1)
        self.assertEqual(self.window.index, 5)
        self.window.go(-1)
        self.assertEqual(self.window.index, 2)
        self.window.go(-1)
        self.window.select_aac_mode(1)
        self.assertEqual(self.window.visible_pages(), [0, 1, 2, 5])
        self.finish_removal()
        self.assertEqual(self.window.visible_pages(), list(range(6)))
        self.assertFalse(self.window.legacy_import_row.isHidden())
        self.assertFalse(self.window.legacy_scripts_card.isHidden())
        self.assertEqual(saved_options, {key: self.window.cfg[key] for key in saved_options})

    def test_failed_or_cancelled_removal_keeps_native_and_legacy_hidden(self):
        self.state(True, True)
        self.window.select_aac_mode(0)
        self.window.select_aac_mode(1)
        self.assertEqual(self.window.cfg["aac_mode"], "native")
        self.assertTrue(self.window.legacy_links.isHidden())
        self.finish_removal(code=1)
        self.assertEqual(self.window.cfg["aac_mode"], "native")
        self.assertEqual(self.window.aac_mode_group.checkedId(), 0)
        self.assertTrue(self.window.legacy_links.isHidden())

    def test_successful_removal_immediately_shows_legacy_shortcuts(self):
        self.state(True, True)
        self.window.select_aac_mode(0)
        self.window.select_aac_mode(1)
        self.finish_removal()
        self.assertTrue(self.window.legacy_links.isVisible())
        buttons = self.window.legacy_links.findChildren(setup.QToolButton)
        self.assertEqual([button.text() for button in buttons], ["Import", "Cache", "Export", "Menu scripts"])
        buttons[1].click()
        self.assertEqual(self.window.index, 3)

    def test_same_page_refresh_does_not_create_new_fade(self):
        animation = self.window.page_animation
        self.window.sync()
        self.assertIs(self.window.page_animation, animation)

    def test_open_resolve_blocks_rollback_before_confirmation_or_process(self):
        self.state(True, True)
        self.window.select_aac_mode(0)
        with patch.object(native, "resolve_processes", return_value=[123]), \
             patch.object(setup.QMessageBox, "information") as info, \
             patch.object(setup.QMessageBox, "question") as confirm:
            NATIVE_OPERATION(self.window, "uninstall")
            info.assert_called_once()
            confirm.assert_not_called()
        self.assertIsNone(self.window.native_process)
        self.assertEqual(self.window.cfg["aac_mode"], "native")

    def test_cancelled_confirmation_never_starts_rollback(self):
        self.state(True, True)
        self.window.select_aac_mode(0)
        with patch.object(native, "resolve_processes", return_value=[]), \
             patch.object(setup.QMessageBox, "question", return_value=setup.QMessageBox.No):
            NATIVE_OPERATION(self.window, "uninstall")
        self.assertIsNone(self.window.native_process)
        self.assertEqual(self.window.cfg["aac_mode"], "native")

    def test_kde_dialog_toggle_is_in_extras_and_preserves_setting(self):
        self.window.open_page(5)
        self.assertTrue(self.window.stack.widget(5).isAncestorOf(self.window.kde_dialog_row))
        self.assertFalse(self.window.stack.widget(2).isAncestorOf(self.window.kde_dialog_row))
        toggle = self.window.kde_dialog_row.findChild(setup.ToggleSwitch)
        original = self.window.cfg["intercept_deliver_browse"]
        toggle.click()
        self.assertEqual(self.window.cfg["intercept_deliver_browse"], not original)
        self.state(True, True)
        self.window.select_aac_mode(0)
        self.assertTrue(self.window.kde_dialog_row.isVisible())
        self.assertEqual(self.window.cfg["intercept_deliver_browse"], not original)

    def test_extras_fit_minimum_size_in_both_workflows(self):
        self.window.resize(760, 560)
        for mode in ("legacy", "native"):
            self.window.cfg["aac_mode"] = mode
            self.window.open_page(5)
            self.app.processEvents()
            page = self.window.stack.widget(5)
            self.assertLessEqual(page.minimumSizeHint().height(), page.height())
            self.assertLessEqual(page.minimumSizeHint().width(), page.width())

    def test_workflow_comparison_opens_from_info_icon_in_either_mode(self):
        self.state()
        self.assertFalse(self.window.legacy_comparison.isVisible())
        self.assertFalse(self.window.native_info.isVisible())
        self.assertFalse(self.window.native_install_btn.isVisible())
        self.assertIn("PCM copies", self.window.legacy_comparison.text())
        self.assertIn("export post-processing", self.window.legacy_comparison.text())
        self.assertIn("AAC export plugin is available for Resolve 20", self.window.legacy_comparison.text())
        self.assertIn("without remux copies", self.window.legacy_comparison.text())
        self.assertIn("Having trouble with the native AAC patch? Try Legacy.", self.window.legacy_comparison.text())
        self.window.workflow_info_btn.click()
        self.assertTrue(self.window.legacy_comparison.isVisible())
        self.assertTrue(self.window.workflow_info.isWindow())
        self.window.workflow_info.close()
        self.state(True, True)
        self.window.select_aac_mode(0)
        self.assertFalse(self.window.legacy_comparison.isVisible())
        self.assertTrue(self.window.native_info.isVisible())
        self.window.workflow_info_btn.click()
        self.assertTrue(self.window.legacy_comparison.isVisible())

    def test_progress_handles_split_messages_and_waiting_for_approval(self):
        self.window.begin_native_progress("install")
        self.window.consume_progress_output('compiler log\nNATIVE_AAC_PROGRESS {"step":"check",')
        self.assertEqual(self.window.progress_bar.value(), 0)
        self.window.consume_progress_output('"state":"done"}\nNATIVE_AAC_PROGRESS {"step":"import","state":"waiting","message":"Approve the administrator dialog."}\n')
        self.assertEqual(self.window.progress_bar.value(), 1)
        self.assertEqual(self.window.progress_rows["import"][1].text(), "Approval needed")
        self.assertEqual(self.window.progress_message.text(), "Approve the administrator dialog.")
        self.window.consume_progress_output('NATIVE_AAC_PROGRESS invalid\nNATIVE_AAC_PROGRESS []\n')
        self.assertEqual(self.window.progress_bar.value(), 1)

    def test_failed_step_does_not_complete_progress(self):
        self.window.begin_native_progress("install")
        self.window.apply_progress_event(dict(step="check", state="done"))
        self.window.apply_progress_event(dict(step="download", state="running"))
        self.window.finish_native_progress(False)
        self.assertEqual(self.window.progress_states["download"], "failed")
        self.assertEqual(self.window.progress_states["build"], "pending")
        self.assertEqual(self.window.progress_bar.value(), 1)
        self.assertTrue(self.window.progress_done_btn.isVisible())

    def test_install_progress_waits_for_final_status_verification(self):
        import json
        self.window.begin_native_progress("install")
        self.window._native_action = "install"
        self.window.consume_progress_output('NATIVE_AAC_PROGRESS {"step":"verify","state":"done"}\n')
        self.assertEqual(self.window.progress_states["verify"], "running")
        self.window._native_action = "status"
        self.window._native_select_after_check = True
        self.window._native_output = json.dumps(dict(supported=True, import_active=True, export_installed=True))
        with patch.object(self.window, "read_native_output"):
            self.window.native_finished(0, setup.QProcess.NormalExit)
        self.assertEqual(self.window.progress_bar.value(), 6)
        self.assertEqual(self.window.cfg["aac_mode"], "native")

    def test_progress_fits_minimum_window_and_dismisses_cleanly(self):
        self.window.resize(760, 560)
        self.window.begin_native_progress("install")
        self.app.processEvents()
        page = self.window.stack.widget(1)
        self.assertFalse(self.window.native_info.isVisible())
        self.assertFalse(self.window.legacy_links.isVisible())
        self.assertLessEqual(page.minimumSizeHint().height(), page.height())
        self.window.finish_native_progress(True)
        self.app.processEvents()
        self.assertLessEqual(page.minimumSizeHint().height(), page.height())
        self.window.progress_done_btn.click()
        self.assertFalse(self.window.native_progress.isVisible())
        self.assertTrue(self.window.legacy_links.isVisible())

    def test_theme_rebuild_keeps_active_progress(self):
        self.window.begin_native_progress("install")
        self.window.apply_progress_event(dict(step="check", state="done"))
        self.window.apply_progress_event(dict(step="download", state="running", message="Downloading..."))
        self.window.rebuild_pages()
        self.assertTrue(self.window.native_progress.isVisible())
        self.assertEqual(self.window.progress_bar.value(), 1)
        self.assertEqual(self.window.progress_states["download"], "running")
        self.assertEqual(self.window.progress_message.text(), "Downloading...")

    def test_info_icon_is_monochrome_and_button_geometry_is_stable(self):
        for palette in (setup.DARK, setup.LIGHT):
            icon = setup.info_icon(palette["MUTED"], palette["TEXT"])
            self.assertFalse(icon.isNull())
            pixels = icon.pixmap(20, 20).toImage()
            opaque = [pixels.pixelColor(x, y) for x in range(pixels.width()) for y in range(pixels.height())
                      if pixels.pixelColor(x, y).alpha() == 255]
            self.assertTrue(opaque)
            self.assertTrue(all(color.name().lower() == palette["MUTED"].lower() for color in opaque))
        self.assertEqual(self.window.workflow_info_btn.size(), setup.QSize(38, 38))
        self.assertEqual(self.window.workflow_info_btn.iconSize(), setup.QSize(20, 20))


if __name__ == "__main__":
    unittest.main()
