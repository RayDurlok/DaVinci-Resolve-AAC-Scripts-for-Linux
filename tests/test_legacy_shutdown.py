import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import resolve_aac_config as config
import resolve_aac_export_watch as export
import resolve_aac_import as importer
import resolve_aac_mediapool_watch as media
import resolve_aac_timeline_watch as timeline
import resolve_aac_watch as folder
import resolve_aac_remux_all as remux_all
import resolve_aac_remux_current as remux_current
import resolve_aac_restore as restore
import resolve_aac_setup as setup
import resolve_aac_tray as tray


class LegacyShutdownTests(unittest.TestCase):
    def setUp(self):
        active = patch.object(config, "load_config", return_value=dict(config.DEFAULT_CONFIG, aac_mode="native"))
        active.start()
        self.addCleanup(active.stop)

    def test_stop_reaches_all_watchers_without_terminating_writers_or_dialogs(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = tuple(Path(directory) / path.name for path in config.LEGACY_STOP_PATHS)
            helper = SimpleNamespace(error=Mock(), watcher_process=Mock(), export_watcher_process=Mock(),
                                     intercept_watcher_process=Mock())
            with patch.object(tray, "LEGACY_STOP_PATHS", paths):
                tray.ResolveAacTray.stop_legacy_tools(helper)
            self.assertEqual(len(paths), 4)
            self.assertTrue(all(path.exists() for path in paths))
            self.assertTrue(helper.watcher_restart_suppressed)
            for process in (helper.watcher_process, helper.export_watcher_process, helper.intercept_watcher_process):
                process.terminate.assert_not_called()

    def test_mode_change_requests_full_shutdown_without_changing_legacy_preferences(self):
        old = dict(config.DEFAULT_CONFIG, aac_mode="legacy", remux_exports=True,
                   watch_manual_resolve=True, intercept_deliver_browse=True)
        helper = Mock(config=old)
        updated = dict(old, aac_mode="native")
        tray.ResolveAacTray.apply_saved_settings(helper, updated)
        helper.stop_legacy_tools.assert_called_once()
        helper.start_export_watcher.assert_not_called()
        helper.stop_intercept_watcher.assert_not_called()
        self.assertTrue(helper.config["watch_manual_resolve"])
        self.assertTrue(helper.config["remux_exports"])

    def test_back_to_legacy_restores_autostart_preferences(self):
        old = dict(config.DEFAULT_CONFIG, aac_mode="native", remux_exports=True)
        helper = Mock(config=old)
        tray.ResolveAacTray.apply_saved_settings(helper, dict(old, aac_mode="legacy"))
        helper.stop_legacy_tools.assert_not_called()
        helper.start_export_watcher.assert_called_once()
        self.assertFalse(helper.watcher_restart_suppressed)

    def test_watcher_entry_points_refuse_native_mode(self):
        for module in (media, timeline, export, folder):
            with self.subTest(watcher=module.__name__), patch.object(sys, "argv", [module.__name__, "--once"]), \
                 patch.object(module, "STOP_PATH") as stop, patch.object(importer, "get_resolve") as resolve:
                self.assertEqual(module.main(), 0)
                stop.unlink.assert_not_called()
                resolve.assert_not_called()

    def test_manual_menu_scripts_refuse_native_without_connecting_to_resolve(self):
        with patch.object(importer, "get_resolve") as resolve:
            for module in (remux_all, remux_current, restore):
                self.assertIn("Legacy menu scripts are disabled", module.run())
            resolve.assert_not_called()

    def test_conversion_does_not_even_probe_in_native_mode(self):
        with patch.object(importer, "ffprobe") as probe:
            result = importer.convert(Path("input.mp4"), Path("out"), Path("."), True, False, False, True)
            self.assertEqual(result.status, "skipped")
            probe.assert_not_called()
        with patch.object(export.subprocess, "run") as encode:
            self.assertIsNone(export.convert(Path("render.mp4"), Mock()))
            encode.assert_not_called()

    def test_finished_import_is_not_relinked_after_switch_to_native(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.mp4"
            source.touch()
            item = Mock()
            with patch.object(media, "legacy_workflow_active", side_effect=[True, False]), \
                 patch.object(media, "convert", return_value=SimpleNamespace(status="converted", output_path=Path("output.mov"))):
                self.assertIsNone(media.replace_media_pool_item(item, raw_path=str(source)))
                item.ReplaceClipPreserveSubClip.assert_not_called()
                item.ReplaceClip.assert_not_called()

    def test_finished_export_is_discarded_without_replacing_original_after_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "render.mp4"
            source.write_bytes(b"original")
            args = SimpleNamespace(replace=True, quiet=True, audio_bitrate="192k")
            def encode(command, **kwargs):
                Path(command[-1]).write_bytes(b"remux")
            with patch.object(export, "legacy_workflow_active", side_effect=[True, False]), \
                 patch.object(export.subprocess, "run", side_effect=encode), \
                 patch.object(export, "verify_fixed", return_value=True), patch.object(export, "log"):
                self.assertIsNone(export.convert(source, args))
            self.assertEqual(source.read_bytes(), b"original")
            self.assertEqual(list(Path(directory).iterdir()), [source])

    def test_legacy_menu_labels_migrate_without_touching_unrelated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_name, target = next(iter(setup.OLD_SCRIPT_LINKS.items()))
            (root / old_name).symlink_to(setup.SCRIPT_DIR / target)
            custom = root / "My script.py"
            custom.write_text("custom")
            with patch.object(setup, "RESOLVE_AAC_SCRIPTS_DIR", root):
                setup.migrate_legacy_menu_labels()
                setup.migrate_legacy_menu_labels()
            renamed = root / f"{Path(old_name).stem} (Legacy).py"
            self.assertTrue(renamed.is_symlink())
            self.assertEqual(renamed.resolve(), setup.SCRIPT_DIR / target)
            self.assertFalse((root / old_name).is_symlink())
            self.assertEqual(custom.read_text(), "custom")


if __name__ == "__main__":
    unittest.main()
