import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import resolve_aac_toolkit_update as update


class ToolkitUpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "test"
        self.root.mkdir()
        update._UPDATE_CHECK_CACHE.clear()

    def archive(self, extra=None):
        archive = self.root / "release.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            for name in ("install_user_tools.sh", "resolve_aac_tray.py", "resolve_aac_config.py"):
                entry = tarfile.TarInfo(f"resolve-aac-tools/{name}")
                data = b"# test release\n"
                entry.size = len(data)
                entry.mode = 0o755
                output.addfile(entry, io.BytesIO(data))
            if extra:
                output.addfile(extra)
        return archive

    def mock_flow(self, kind="rpm"):
        mocks = {}
        for name, kwargs in (
            ("installation_kind", {"return_value": kind}),
            ("require_closed", {}), ("require_idle", {}),
            ("operation_lock", {"side_effect": nullcontext}),
            ("wait_for_changes", {"side_effect": nullcontext}),
            ("stop_tray", {}), ("restart_tray", {}),
            ("refresh_menu_links", {}),
        ):
            context = patch.object(update, name, **kwargs)
            mocks[name] = context.start()
            self.addCleanup(context.stop)
        for target, kwargs in (
            ("shutil.which", {"return_value": "/usr/bin/tool"}),
            ("subprocess.run", {}),
        ):
            context = patch("resolve_aac_toolkit_update." + target, **kwargs)
            mocks[target] = context.start()
            self.addCleanup(context.stop)
        return mocks

    def test_source_checkout_is_never_overwritten(self):
        (self.root / ".git").write_text("gitdir: /elsewhere")
        app = self.root / "scripts"
        app.mkdir()
        with self.assertRaisesRegex(RuntimeError, "source checkout"):
            update.installation_kind(app)

    def test_rpm_detection_checks_ownership_of_active_runtime(self):
        with patch.object(update.shutil, "which", return_value="rpm"), patch.object(
                update.subprocess, "run", return_value=Mock(returncode=0, stdout=update.PACKAGE)) as run:
            self.assertEqual(update.installation_kind(self.root), "rpm")
            self.assertIn(str(self.root / "resolve_aac_tray.py"), run.call_args.args[0])
        with patch.object(update.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Unknown installation"):
                update.installation_kind(self.root)
            (self.root / "install_user_tools.sh").touch()
            self.assertEqual(update.installation_kind(self.root), "archive")

    def test_archive_extracts_only_expected_files_and_keeps_execute_permission(self):
        app = update.extract_archive(self.archive(), self.root / "unpacked")
        self.assertEqual(app.name, "resolve-aac-tools")
        self.assertEqual((app / "install_user_tools.sh").stat().st_mode & 0o777, 0o755)

    def test_archive_rejects_traversal_links_absolute_paths_and_duplicates(self):
        for name, kind in (
            ("resolve-aac-tools/../../escaped", tarfile.REGTYPE),
            ("/tmp/escaped", tarfile.REGTYPE),
            ("other-root/file", tarfile.REGTYPE),
            ("resolve-aac-tools/link", tarfile.SYMTYPE),
            ("resolve-aac-tools/hardlink", tarfile.LNKTYPE),
            ("resolve-aac-tools/install_user_tools.sh", tarfile.REGTYPE),
        ):
            with self.subTest(name=name):
                entry = tarfile.TarInfo(name)
                entry.type = kind
                entry.linkname = "/tmp/escaped"
                with self.assertRaisesRegex(RuntimeError, "Unsafe"):
                    update.extract_archive(self.archive(entry), self.root / "unpacked")
                self.assertFalse((self.root / "unpacked").exists())

    def test_download_verifies_checksum(self):
        payload = b"release data"
        with patch.object(update.urllib.request, "urlopen", return_value=io.BytesIO(payload)):
            update.download_archive("https://example.invalid", hashlib.sha256(payload).hexdigest(), self.root / "ok")
        with patch.object(update.urllib.request, "urlopen", return_value=io.BytesIO(payload)):
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                update.download_archive("https://example.invalid", "0" * 64, self.root / "bad")

    def test_release_metadata_rejects_untrusted_asset_url_or_missing_digest(self):
        release = {"tag_name": "v0.4.0", "assets": [{"name": update.ASSET,
            "browser_download_url": f"https://github.com/{update.REPOSITORY}/releases/download/v0.4.0/{update.ASSET}",
            "digest": "sha256:" + "a" * 64}]}
        with patch.object(update.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(release).encode())):
            self.assertEqual(update.latest_release()[2], "a" * 64)
        release["assets"][0]["digest"] = None
        with patch.object(update.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(release).encode())):
            with self.assertRaisesRegex(RuntimeError, "no SHA-256"):
                update.latest_release()
        release["assets"][0]["browser_download_url"] = "https://example.invalid/malware"
        with patch.object(update.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(release).encode())):
            with self.assertRaisesRegex(RuntimeError, "Unexpected"):
                update.latest_release()

    def test_archive_update_available_only_for_newer_stable_version(self):
        with patch.object(update, "installation_kind", return_value="archive"):
            for version, expected in (("v99.0.0", True), (update.APP_VERSION, False), ("v0.0.1", False)):
                with self.subTest(version=version), patch.object(update, "latest_release", return_value=(version, "url", "hash")):
                    self.assertEqual(update.update_available(self.root), expected)

    def test_rpm_check_only_shows_updates_confirmed_by_package_manager(self):
        with patch.object(update, "installation_kind", return_value="rpm"), patch.object(update.shutil, "which", return_value="dnf"):
            for status, expected in ((100, True), (0, False), (1, False)):
                with self.subTest(status=status), patch.object(update.subprocess, "run", return_value=Mock(returncode=status)) as run:
                    self.assertEqual(update.update_available(self.root), expected)
                    self.assertEqual(run.call_args.args[0], ["dnf", "--quiet", "--refresh", "check-update", update.PACKAGE])
                    self.assertEqual(run.call_args.kwargs["timeout"], 60)

    def test_update_check_is_cached_and_rechecks_after_expiry(self):
        with patch.object(update, "update_available", side_effect=[True, False]) as check, patch.object(
                update.time, "monotonic", side_effect=[0, 10, 901, 902]):
            self.assertTrue(update.cached_update_available(self.root))
            self.assertTrue(update.cached_update_available(self.root))
            self.assertFalse(update.cached_update_available(self.root))
        self.assertEqual(check.call_count, 2)

    def test_update_check_errors_hide_button_and_are_cached(self):
        with patch.object(update, "update_available", side_effect=OSError("offline")) as check:
            self.assertFalse(update.cached_update_available(self.root))
            self.assertFalse(update.cached_update_available(self.root))
            check.assert_called_once()

    def test_update_check_runs_off_main_thread(self):
        complete = threading.Event()
        main_thread = threading.get_ident()
        calls = []
        def report(result):
            calls.append((threading.get_ident(), result))
            complete.set()
        with patch.object(update, "cached_update_available", return_value=True):
            update.check_update_async(self.root, report)
            self.assertTrue(complete.wait(3))
        self.assertEqual(calls[0][1], True)
        self.assertNotEqual(calls[0][0], main_thread)

    def test_cancel_does_not_stop_tray_or_install(self):
        mocks = self.mock_flow()
        with patch("builtins.input", return_value="n"):
            update.perform_update(self.root, 123)
        mocks["stop_tray"].assert_not_called()
        mocks["restart_tray"].assert_not_called()
        mocks["subprocess.run"].assert_not_called()

    def test_rpm_update_restarts_same_installation(self):
        mocks = self.mock_flow()
        with patch("builtins.input", return_value="y"):
            update.perform_update(self.root, 123)
        mocks["stop_tray"].assert_called_once_with(123)
        mocks["subprocess.run"].assert_called_once_with(
            ["sudo", "dnf", "--refresh", "upgrade", update.PACKAGE], check=True)
        mocks["restart_tray"].assert_called_once_with(self.root)

    def test_failed_package_update_still_restarts_toolkit(self):
        mocks = self.mock_flow()
        mocks["subprocess.run"].side_effect = subprocess.CalledProcessError(1, "dnf")
        with patch("builtins.input", return_value="y"), self.assertRaises(subprocess.CalledProcessError):
            update.perform_update(self.root, 123)
        mocks["restart_tray"].assert_called_once_with(self.root)

    def test_resolve_or_conversion_blocks_update_before_stop(self):
        mocks = self.mock_flow()
        for name in ("require_closed", "require_idle"):
            with self.subTest(name=name):
                mocks[name].side_effect = RuntimeError("busy")
                with self.assertRaisesRegex(RuntimeError, "busy"):
                    update.perform_update(self.root, 123)
                mocks["stop_tray"].assert_not_called()
                mocks["subprocess.run"].assert_not_called()
                mocks[name].side_effect = None

    def test_up_to_date_archive_does_not_stop_tray(self):
        mocks = self.mock_flow("archive")
        with patch.object(update, "latest_release", return_value=(update.APP_VERSION, "url", "hash")):
            update.perform_update(self.root, 123)
        mocks["stop_tray"].assert_not_called()
        mocks["subprocess.run"].assert_not_called()

    def test_download_failure_leaves_running_installation_untouched(self):
        mocks = self.mock_flow("archive")
        with patch.object(update, "latest_release", return_value=("v99.0.0", "url", "hash")), patch.object(
                update, "download_archive", side_effect=OSError("network unavailable")):
            with self.assertRaisesRegex(OSError, "network unavailable"):
                update.perform_update(self.root, 123)
        mocks["stop_tray"].assert_not_called()
        mocks["restart_tray"].assert_not_called()
        mocks["subprocess.run"].assert_not_called()

    def test_parallel_update_cannot_install(self):
        mocks = self.mock_flow()
        mocks["operation_lock"].side_effect = RuntimeError("another update is running")
        with self.assertRaisesRegex(RuntimeError, "another update"):
            update.perform_update(self.root, 123)
        mocks["stop_tray"].assert_not_called()
        mocks["subprocess.run"].assert_not_called()

    def test_tarball_install_retains_runtime_and_never_runs_from_temporary_download(self):
        mocks = self.mock_flow("archive")
        archive = self.archive()
        data_home = self.root / "data"
        config = self.root / "config.json"
        config.write_text('{"aac_mode": "native"}')
        with patch.object(update, "latest_release", return_value=("v99.0.0", "url", "hash")), patch.object(
                update, "download_archive", side_effect=lambda url, digest, target: target.write_bytes(archive.read_bytes())), patch.dict(
                os.environ, {"XDG_DATA_HOME": str(data_home)}), patch("builtins.input", return_value="yes"):
            update.perform_update(self.root, 123)
        arguments = mocks["subprocess.run"].call_args
        installed = arguments.kwargs["cwd"]
        self.assertTrue(installed.is_relative_to(data_home))
        self.assertTrue((installed / "resolve_aac_tray.py").is_file())
        self.assertEqual(arguments.kwargs["env"]["RESOLVE_AAC_INSTALL_NO_START"], "1")
        mocks["restart_tray"].assert_called_once_with(installed)
        self.assertEqual(config.read_text(), '{"aac_mode": "native"}')

    def test_shutdown_timeout_never_kills_tray(self):
        request = self.root / "stop.request"
        with patch.object(update, "STOP_REQUEST", request), patch.object(update, "process_alive", return_value=True), patch.object(
                update.time, "monotonic", side_effect=[0, 31]):
            with self.assertRaisesRegex(RuntimeError, "did not close"):
                update.stop_tray(123)
        self.assertFalse(request.exists())

    def test_menu_shortcuts_follow_updated_archive_but_user_files_stay_untouched(self):
        old, new, menu = [self.root / name for name in ("old", "new", "menu")]
        for folder in (old, new, menu):
            folder.mkdir()
        (new / "resolve_aac_remux_all.py").touch()
        link = menu / "Remux All (Legacy).py"
        link.symlink_to(old / "resolve_aac_remux_all.py")
        custom = menu / "Custom.py"
        custom.write_text("user script")
        external = menu / "External.py"
        external.symlink_to(self.root / "outside.py")
        update.refresh_menu_links(old, new, menu)
        self.assertEqual(link.resolve(), new / "resolve_aac_remux_all.py")
        self.assertEqual(custom.read_text(), "user script")
        self.assertEqual(external.resolve(), self.root / "outside.py")

    def test_busy_check_distinguishes_toolkit_conversions_from_unrelated_ffmpeg(self):
        proc = self.root / "proc"
        for pid, ppid, args in ((10, 1, ["python3", "resolve_aac_export_watch.py"]), (11, 10, ["ffmpeg", "-i", "video.mov"])):
            entry = proc / str(pid)
            entry.mkdir(parents=True)
            (entry / "cmdline").write_bytes("\0".join(args).encode())
            (entry / "stat").write_text(f"{pid} (process) S {ppid}")
        with self.assertRaisesRegex(RuntimeError, "conversion is still running"):
            update.require_idle(proc)
        (proc / "10" / "cmdline").write_bytes(b"unrelated-app\0")
        update.require_idle(proc)


if __name__ == "__main__":
    unittest.main()
