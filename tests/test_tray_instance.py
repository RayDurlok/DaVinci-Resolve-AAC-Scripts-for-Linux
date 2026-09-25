import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import resolve_aac_tray as tray
import resolve_aac_setup as setup


class TrayInstanceTests(unittest.TestCase):
    def test_lock_is_cross_process_and_released_after_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            code = (
                "import sys,time; from pathlib import Path; "
                "sys.path.insert(0,sys.argv[2]); import resolve_aac_tray as t; "
                "t.CONFIG_DIR=Path(sys.argv[1]); lock=t.acquire_tray_lock(); "
                "print('locked' if lock else 'duplicate',flush=True); time.sleep(60)"
            )
            process = subprocess.Popen([sys.executable, "-c", code, directory, str(tray.SCRIPT_DIR)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), "locked")
                with patch.object(tray, "CONFIG_DIR", Path(directory)):
                    self.assertIsNone(tray.acquire_tray_lock())
                    process.kill()
                    process.communicate(timeout=5)
                    lock = tray.acquire_tray_lock()
                    self.assertIsNotNone(lock)
                    lock.close()
                    self.assertTrue((Path(directory) / "tray.lock").exists())
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)

    def test_repeated_launch_forwards_request_without_creating_application(self):
        for args, start, settings in (([], False, True), (["--settings"], False, True),
                                      (["--start-resolve"], True, False),
                                      (["--start-resolve", "--settings"], True, True)):
            with self.subTest(args=args), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with patch.object(tray, "acquire_tray_lock", return_value=None), \
                     patch.object(tray, "START_REQUEST_PATH", root / "start"), \
                     patch.object(tray, "SETTINGS_REQUEST_PATH", root / "settings"), \
                     patch.object(tray, "ResolveAacTray") as application:
                    self.assertEqual(tray.main(args), 0)
                    application.assert_not_called()
                    self.assertEqual((root / "start").exists(), start)
                    self.assertEqual((root / "settings").exists(), settings)

    def test_owner_holds_lock_until_application_exits(self):
        lock = Mock()
        with patch.object(tray, "acquire_tray_lock", return_value=lock), \
             patch.object(tray, "ResolveAacTray") as application:
            def run():
                lock.close.assert_not_called()
                return 0
            application.return_value.run.side_effect = run
            self.assertEqual(tray.main([]), 0)
            lock.close.assert_called_once()

    def test_failed_start_releases_lock(self):
        lock = Mock()
        with patch.object(tray, "acquire_tray_lock", return_value=lock), \
             patch.object(tray, "ResolveAacTray", side_effect=RuntimeError("startup failed")):
            with self.assertRaises(RuntimeError):
                tray.main([])
            lock.close.assert_called_once()

    def test_forwarded_requests_consumed_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = SimpleNamespace(start_resolve=Mock(), open_settings=Mock())
            with patch.object(tray, "START_REQUEST_PATH", root / "start"), \
                 patch.object(tray, "SETTINGS_REQUEST_PATH", root / "settings"):
                (root / "start").touch()
                (root / "settings").touch()
                tray.ResolveAacTray.consume_start_request(helper)
                tray.ResolveAacTray.consume_start_request(helper)
                helper.start_resolve.assert_called_once()
                helper.open_settings.assert_called_once()

    def test_standalone_settings_uses_same_instance_entry_point(self):
        with patch.object(sys, "argv", ["resolve_aac_setup.py"]), patch.object(tray, "main", return_value=0) as main:
            self.assertEqual(setup.main(), 0)
            main.assert_called_once_with(["--settings"])

    def test_existing_settings_window_is_reused(self):
        helper = SimpleNamespace(setup_window=Mock())
        tray.ResolveAacTray.open_settings(helper)
        helper.setup_window.raise_.assert_called_once()
        helper.setup_window.activateWindow.assert_called_once()


if __name__ == "__main__":
    unittest.main()
