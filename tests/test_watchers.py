import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import resolve_aac_mediapool_watch as media_watch
import resolve_aac_tray as tray_module
import resolve_render_location_watch as dialog_watch
import set_render_location


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.log_patch = patch.object(media_watch, "log")
        self.log_patch.start()
        active = patch.object(media_watch, "legacy_workflow_active", return_value=True)
        active.start()
        self.addCleanup(active.stop)
        stop = patch.object(media_watch, "STOP_PATH", Mock(exists=Mock(return_value=False)))
        stop.start()
        self.addCleanup(stop.stop)

    def tearDown(self):
        self.log_patch.stop()

    def test_retry_delay_is_bounded(self):
        self.assertEqual(media_watch.retry_delay(1), 5.0)
        self.assertEqual(media_watch.retry_delay(2), 10.0)
        self.assertEqual(media_watch.retry_delay(1000), 60.0)

    def test_scan_summary_records_first_pass(self):
        state = media_watch.new_scan_state()
        with patch.object(media_watch.time, "monotonic", return_value=12.5):
            self.assertEqual(media_watch.finish_scan(state, 25, 0, 10.0), 0)
        media_watch.log.assert_called_once_with(
            "MediaPool scan complete: 25 item(s), 0 remuxed, 0 offline, 2.50s"
        )

    def test_incremental_scan_puts_newest_current_folder_clip_first(self):
        old_items = [object(), object()]
        newest = object()

        class Folder:
            @staticmethod
            def GetUniqueId():
                return "root"

            @staticmethod
            def GetName():
                return "Root"

            @staticmethod
            def GetClipList():
                return [*old_items, newest]

            @staticmethod
            def GetSubFolderList():
                return []

        folder = Folder()

        class MediaPool:
            @staticmethod
            def GetRootFolder():
                return folder

            @staticmethod
            def GetCurrentFolder():
                return folder

        state = media_watch.new_scan_state()
        items = media_watch.collect_incremental_items(
            MediaPool(),
            state,
            fast_limit=1,
            background_limit=0,
            rescan_seconds=30,
        )
        self.assertEqual(items, [newest])

    def test_failed_replace_is_retried(self):
        args = SimpleNamespace(retry=False, output_dir=None, cache_dir=None, overwrite=False, quiet=True)
        state = media_watch.new_scan_state()

        class MediaPool:
            @staticmethod
            def GetRootFolder():
                return object()

        item = object()
        source = str(Path(__file__).resolve())
        replacement = Path("/tmp/resolve-aac-test-remux.mov")
        with (
            patch.object(media_watch, "get_context", return_value=MediaPool()),
            patch.object(media_watch, "iter_media_pool_items", return_value=[item]),
            patch.object(media_watch, "item_process_key", return_value="item"),
            patch.object(media_watch, "media_pool_signature", return_value=("item",)),
            patch.object(media_watch, "media_pool_item_path", return_value=source),
            patch.object(media_watch, "item_online_state", return_value="online"),
            patch.object(media_watch, "is_generated_remux_path", return_value=False),
            patch.object(
                media_watch,
                "replace_media_pool_item",
                side_effect=[RuntimeError("temporary API failure"), replacement],
            ) as replace,
        ):
            self.assertEqual(media_watch.scan_once(args, state), 0)
            self.assertNotIn("item", state["processed"])
            self.assertEqual(state["failures"]["item"], 1)

            state["retry_after"]["item"] = 0
            self.assertEqual(media_watch.scan_once(args, state), 1)
            self.assertIn("item", state["processed"])
            self.assertNotIn("item", state["retry_after"])
            self.assertEqual(replace.call_count, 2)

    def test_polling_properties_never_request_full_property_map(self):
        source = str(Path(__file__).resolve())

        class Item:
            calls = []

            @classmethod
            def GetClipProperty(cls, key=None):
                cls.calls.append(key)
                if key == "File Path":
                    return source
                if key == "Status":
                    return ""
                raise AssertionError("full GetClipProperty() must not be used by the watcher")

        item = Item()
        self.assertEqual(media_watch.media_pool_item_path(item), source)
        self.assertEqual(media_watch.item_online_state(item), "online")
        self.assertEqual(item.calls, ["File Path", "File Path", "Status"])

    def test_new_import_is_prioritized_over_existing_backlog(self):
        args = SimpleNamespace(
            retry=False,
            output_dir=None,
            cache_dir=None,
            overwrite=False,
            quiet=True,
            batch_size=1,
        )
        state = media_watch.new_scan_state()
        old_a, old_b, new_clip = object(), object(), object()
        scans = [[old_a, old_b], [old_a, old_b, new_clip]]
        keys = {old_a: "old-a", old_b: "old-b", new_clip: "new"}
        paths = {old_a: "/tmp/old-a.mov", old_b: "/tmp/old-b.mov", new_clip: "/tmp/new.mov"}
        converted = []

        class MediaPool:
            @staticmethod
            def GetRootFolder():
                return object()

        def replace(item, **_kwargs):
            converted.append(keys[item])
            return Path(paths[item] + ".remux.mov")

        with (
            patch.object(media_watch, "get_context", return_value=MediaPool()),
            patch.object(media_watch, "iter_media_pool_items", side_effect=scans),
            patch.object(media_watch, "item_process_key",
                         side_effect=lambda item, *_args: keys[item]),
            patch.object(media_watch, "media_pool_signature",
                         side_effect=lambda items: tuple(keys[item] for item in items)),
            patch.object(media_watch, "media_pool_item_path", side_effect=lambda item: paths[item]),
            patch.object(media_watch, "item_online_state", return_value="online"),
            patch.object(media_watch, "is_generated_remux_path", return_value=False),
            patch.object(media_watch, "replace_media_pool_item", side_effect=replace),
        ):
            self.assertEqual(media_watch.scan_once(args, state), 1)
            self.assertEqual(media_watch.scan_once(args, state), 1)

        self.assertEqual(converted, ["old-a", "new"])

    def test_memory_guard_recycles_above_limit(self):
        with (
            patch.object(media_watch, "current_rss_mib", return_value=300),
            patch.object(media_watch.os, "execv") as execv,
        ):
            self.assertTrue(media_watch.recycle_if_memory_high(256))
            execv.assert_called_once()

    def test_memory_guard_can_be_disabled(self):
        with patch.object(media_watch.os, "execv") as execv:
            self.assertFalse(media_watch.recycle_if_memory_high(0))
            execv.assert_not_called()


class DialogTests(unittest.TestCase):
    def test_relink_dialog_is_not_intercepted(self):
        self.assertEqual(dialog_watch.INTERCEPT_TITLES, {dialog_watch.FILE_DESTINATION_TITLE})

    def test_native_picker_is_not_opened_while_resolve_dialog_remains(self):
        resolve = object()
        with (
            patch.object(dialog_watch, "close_resolve_dialog", return_value=False),
            patch.object(dialog_watch, "wait_for_dialog_to_disappear") as wait,
            patch.object(dialog_watch.srl, "pick_save_path") as picker,
        ):
            self.assertIs(dialog_watch.handle_file_destination_intercept(resolve, True), resolve)
            picker.assert_not_called()
            wait.assert_called_once_with(dialog_watch.FILE_DESTINATION_TITLE)

    def test_missing_xprop_is_reported_as_no_window(self):
        with patch.object(dialog_watch.subprocess, "run", side_effect=FileNotFoundError):
            self.assertEqual(
                dialog_watch.find_intercept_window(dialog_watch.INTERCEPT_TITLES),
                (None, None),
            )

    def test_fallback_picker_uses_utf8(self):
        completed = SimpleNamespace(returncode=0, stdout="/tmp/output.mov\n")

        def which(name):
            return "/usr/bin/kdialog" if name == "kdialog" else None

        with (
            patch.object(set_render_location, "_portal_save_file", side_effect=RuntimeError("no portal")),
            patch.object(set_render_location.shutil, "which", side_effect=which),
            patch.object(set_render_location.subprocess, "run", return_value=completed) as run,
        ):
            self.assertEqual(set_render_location.pick_save_path("/tmp"), "/tmp/output.mov")
            self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
            self.assertEqual(run.call_args.kwargs["errors"], "replace")

    def test_last_render_directory_supports_unicode(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            target = root / "Exports mit Umlaut ö"
            target.mkdir()
            state_file = root / "last_render_location"

            with patch.object(set_render_location, "STATE_FILE", state_file):
                set_render_location.save_start_dir(str(target))
                self.assertEqual(state_file.read_bytes(), (str(target) + "\n").encode("utf-8"))
                self.assertEqual(set_render_location.load_start_dir(None), str(target))

    def test_failed_state_write_keeps_previous_directory(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            state_file = Path(raw_tmp) / "last_render_location"
            state_file.write_text("/previous\n", encoding="utf-8")

            with (
                patch.object(set_render_location, "STATE_FILE", state_file),
                patch.object(Path, "write_text", side_effect=OSError("disk full")),
            ):
                set_render_location.save_start_dir("/new")

            self.assertEqual(state_file.read_text(encoding="utf-8"), "/previous\n")


class TrayHealthTests(unittest.TestCase):
    def make_tray(self, *, suppressed=False, watcher_running=False):
        tray = tray_module.ResolveAacTray.__new__(tray_module.ResolveAacTray)
        tray.config = {"watch_manual_resolve": True}
        tray.process = None
        tray.watcher_process = None
        tray.watcher_restart_suppressed = suppressed
        tray.manual_resolve_was_running = True
        tray.manual_resolve_identity = ("123", "100")
        tray.resolve_process_identity = lambda: ("123", "100")
        tray.resolve_is_running = lambda: tray.resolve_process_identity() is not None
        tray.watcher_is_running = lambda: watcher_running
        tray.start_watcher_for_manual_resolve = Mock()
        return tray

    def test_dead_watcher_is_restarted_while_resolve_runs(self):
        tray = self.make_tray()
        tray.check_manual_resolve()
        tray.start_watcher_for_manual_resolve.assert_called_once()

    def test_manual_stop_suppresses_health_restart(self):
        tray = self.make_tray(suppressed=True)
        tray.check_manual_resolve()
        tray.start_watcher_for_manual_resolve.assert_not_called()

    def test_fast_resolve_restart_clears_manual_stop_suppression(self):
        tray = self.make_tray(suppressed=True)
        tray.resolve_process_identity = lambda: ("456", "200")

        tray.check_manual_resolve()

        self.assertFalse(tray.watcher_restart_suppressed)
        self.assertEqual(tray.manual_resolve_identity, ("456", "200"))
        tray.start_watcher_for_manual_resolve.assert_called_once()

    def test_dialog_watcher_does_not_depend_on_media_watcher(self):
        tray = tray_module.ResolveAacTray.__new__(tray_module.ResolveAacTray)
        tray.config = {"intercept_deliver_browse": True}
        tray.resolve_is_running = Mock(return_value=True)
        tray.intercept_watcher_is_running = Mock(return_value=False)
        tray.start_intercept_watcher = Mock()
        tray.stop_intercept_watcher = Mock()

        tray.reconcile_intercept_watcher()

        tray.start_intercept_watcher.assert_called_once_with(notify=False)
        tray.stop_intercept_watcher.assert_not_called()


if __name__ == "__main__":
    unittest.main()
