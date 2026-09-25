import hashlib
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import resolve_aac_config as config
import resolve_aac_native as native
import resolve_aac_tray as tray


class ConfigTests(unittest.TestCase):
    def test_architecture_notice_is_once_per_migration_not_every_launch(self):
        self.assertFalse(config.should_show_native_update(dict(config.DEFAULT_CONFIG)))
        old = dict(config.DEFAULT_CONFIG, setup_completed=True)
        self.assertTrue(config.should_show_native_update(old))
        old["native_aac_notice_version"] = config.NATIVE_AAC_NOTICE_VERSION
        self.assertFalse(config.should_show_native_update(old))
        old["native_aac_notice_version"] += 1
        self.assertFalse(config.should_show_native_update(old))
        old["native_aac_notice_version"] = "invalid"
        self.assertTrue(config.should_show_native_update(old))

    def test_old_configs_keep_legacy(self):
        self.assertTrue(config.legacy_enabled({"watch_manual_resolve": True}))
        self.assertFalse(config.legacy_enabled({"aac_mode": "native"}))

    def test_modes_roundtrip_without_losing_legacy_options(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(config, "CONFIG_DIR", root), patch.object(config, "CONFIG_PATH", root / "config.json"):
                config.save_config({"aac_mode": "native", "remux_exports": True, "use_cache": True})
                saved = config.load_config()
                self.assertEqual(saved["aac_mode"], "native")
                self.assertTrue(saved["remux_exports"])
                self.assertTrue(saved["use_cache"])
                with self.assertRaises(ValueError):
                    config.save_config({"aac_mode": "bogus"})
                (root / "config.json").write_text(json.dumps({"aac_mode": "bogus"}))
                self.assertEqual(config.load_config()["aac_mode"], "legacy")


class InstallerTests(unittest.TestCase):
    def test_verify_before_caching(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "release.tar.gz"
            with patch.object(native.urllib.request, "urlopen", return_value=io.BytesIO(b"bad")):
                with self.assertRaisesRegex(RuntimeError, "checksum"):
                    native.download_verified("https://example.invalid/release", target, "0" * 64)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_suffix(".gz.part").exists())
            content = b"verified release"
            digest = hashlib.sha256(content).hexdigest()
            with patch.object(native.urllib.request, "urlopen", return_value=io.BytesIO(content)):
                native.download_verified("https://example.invalid/release", target, digest)
            with patch.object(native.urllib.request, "urlopen") as download:
                native.download_verified("https://example.invalid/release", target, digest)
                download.assert_not_called()

    def test_tar_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "evil.tar"
            with tarfile.open(archive, "w") as output:
                info = tarfile.TarInfo("../escape")
                info.size = 1
                output.addfile(info, io.BytesIO(b"x"))
            with self.assertRaises(tarfile.FilterError):
                native.extract_verified(archive, root / "dest")
            self.assertFalse((root / "escape").exists())

    def test_process_identity_survives_renamed_gui_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            for pid, executable in (("123", "/opt/resolve/bin/resolve"),
                                    ("124", "/opt/resolve/bin/resolve (deleted)"),
                                    ("125", "/usr/bin/python3")):
                (proc / pid).mkdir()
                (proc / pid / "exe").symlink_to(executable)
                (proc / pid / "comm").write_text("GUI Thread")
            self.assertEqual(sorted(native.resolve_processes(proc=proc)), [123, 124])

    def test_install_refuses_running_resolve_before_download(self):
        with patch.object(native, "resolve_processes", return_value=[123]), patch.object(native, "prepare_package") as prepare:
            with self.assertRaisesRegex(RuntimeError, "Close Resolve"):
                native.install()
            prepare.assert_not_called()

    def test_unknown_versions_fail_closed(self):
        with patch.object(native, "require_closed"), patch.object(native, "resolve_info", return_value=("22.0.0", "studio")), patch.object(native, "prepare_package") as prepare:
            with self.assertRaisesRegex(RuntimeError, "Studio 21"):
                native.install()
            prepare.assert_not_called()

    def test_status_does_not_accept_partial_patch(self):
        with patch.object(native, "resolve_info", return_value=("21.1.0", "studio")), patch.object(native, "find_package", return_value=Path("/package")), patch.object(native.shutil, "which", return_value="/tool"):
            for output, active in (("AAC support: ACTIVE", True),
                                   ("mixed library set\nAAC support: ACTIVE", False),
                                   ("binary patched but FFmpeg libs lack AAC", False)):
                with patch.object(native.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=output, stderr="")):
                    self.assertEqual(native.native_status()["import_active"], active)

    def test_build_finishes_before_patch_or_plugin_install(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            with patch.object(native, "DATA_DIR", Path(directory)), patch.object(native, "require_closed"), patch.object(native, "resolve_info", return_value=("21.1.0", "studio")), patch.object(native, "supported", return_value=True), patch.object(native.shutil, "which", return_value="/tool"), patch.object(native, "prepare_package", return_value=Path(directory)), patch.object(native, "build_export", side_effect=lambda *_: calls.append("build") or Path(directory) / "plugin"), patch.object(native, "native_status", side_effect=[{"import_active": False}, {"import_active": True}, {"import_active": True, "export_installed": True}]), patch.object(native, "privileged", side_effect=lambda action, _: calls.append(action)), patch.object(native, "RESOLVE_ROOT", Path(directory)):
                native.install()
            self.assertEqual(calls, ["build", "install-patch", "install-export"])

    def test_failed_build_never_modifies_resolve(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(native, "DATA_DIR", Path(directory)), patch.object(native, "require_closed"), patch.object(native, "resolve_info", return_value=("21.1.0", "studio")), patch.object(native, "supported", return_value=True), patch.object(native.shutil, "which", return_value="/tool"), patch.object(native, "prepare_package", return_value=Path(directory)), patch.object(native, "build_export", side_effect=RuntimeError("build failed")), patch.object(native, "privileged") as privileged, patch.object(native, "RESOLVE_ROOT", Path(directory)):
                with self.assertRaisesRegex(RuntimeError, "build failed"):
                    native.install()
                privileged.assert_not_called()

    def test_uninstall_handles_both_components(self):
        with patch.object(native, "require_closed"), patch.object(native, "prepare_package", return_value=Path("/package")), patch.object(native, "privileged") as operation, patch.object(native, "native_status", return_value={"import_active": False, "export_installed": False}):
            native.uninstall()
            operation.assert_called_once_with("uninstall", Path("/package"))

    def test_uninstall_cannot_report_success_with_one_component_left(self):
        with patch.object(native, "require_closed"), patch.object(native, "prepare_package", return_value=Path("/package")), patch.object(native, "privileged"), patch.object(native, "native_status", return_value={"import_active": True, "export_installed": False}):
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                native.uninstall()


class NativeWatcherTests(unittest.TestCase):
    def test_update_notice_acknowledges_without_changing_workflow(self):
        for open_settings in (False, True):
            old = dict(config.DEFAULT_CONFIG, setup_completed=True, remux_exports=True)
            helper = SimpleNamespace(config=old.copy(), setup_window=None, open_native_settings=Mock())
            with patch.object(tray, "QMessageBox") as message, patch.object(tray, "load_config", return_value=old.copy()), patch.object(tray, "save_config") as save:
                dialog = message.return_value
                settings_button = object()
                dialog.addButton.side_effect = [settings_button, object()]
                dialog.clickedButton.return_value = settings_button if open_settings else None
                tray.ResolveAacTray.show_native_update_notice(helper)
                expected = dict(old, native_aac_notice_version=config.NATIVE_AAC_NOTICE_VERSION)
                save.assert_called_once_with(expected)
                self.assertEqual(helper.config, expected)
                self.assertEqual(helper.open_native_settings.call_count, int(open_settings))
                dialog.exec.assert_called_once()
                tray.ResolveAacTray.show_native_update_notice(helper)
                dialog.exec.assert_called_once()

    def test_native_tray_hides_legacy_menu_and_cache_tooltip(self):
        helper = SimpleNamespace(config=dict(config.DEFAULT_CONFIG, aac_mode="native"), process=None,
                                 watcher_is_running=Mock(return_value=False),
                                 export_watcher_is_running=Mock(return_value=False))
        for name in ("legacy_menu", "status_action", "start_action", "watch_manual_action", "remux_exports_action",
                     "stop_action", "open_cache_action", "tray", "update_export_plugin_action", "update_resolve_font_action"):
            setattr(helper, name, Mock())
        tray.ResolveAacTray.update_status(helper)
        helper.legacy_menu.menuAction().setVisible.assert_called_with(False)
        self.assertNotIn("remux", helper.tray.setToolTip.call_args.args[0])
        self.assertNotIn("Output", helper.tray.setToolTip.call_args.args[0])
        helper.config["aac_mode"] = "legacy"
        tray.ResolveAacTray.update_status(helper)
        helper.legacy_menu.menuAction().setVisible.assert_called_with(True)

    def helper(self):
        return SimpleNamespace(config={"aac_mode": "native", "remux_exports": True, "watch_manual_resolve": True},
                               watcher_path=Mock(), export_watcher_path=Mock())

    def test_native_mode_never_starts_conversion_watchers(self):
        helper = self.helper()
        tray.ResolveAacTray.start_watcher_for_manual_resolve(helper)
        tray.ResolveAacTray.start_export_watcher(helper)
        helper.watcher_path.assert_not_called()
        helper.export_watcher_path.assert_not_called()

    def test_native_mode_uses_plain_launcher(self):
        helper = self.helper()
        self.assertEqual(tray.ResolveAacTray.launcher_path(helper).name, "resolve-with-fonts.sh")
        helper.config["aac_mode"] = "legacy"
        self.assertEqual(tray.ResolveAacTray.launcher_path(helper).name, "resolve-with-aac-mediapool-watch.sh")

    def test_native_mode_ignores_manual_start_watch_setting(self):
        helper = self.helper()
        helper.resolve_process_identity = Mock(return_value=(123, "generation"))
        helper.start_watcher_for_manual_resolve = Mock()
        tray.ResolveAacTray.check_manual_resolve(helper)
        helper.start_watcher_for_manual_resolve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
