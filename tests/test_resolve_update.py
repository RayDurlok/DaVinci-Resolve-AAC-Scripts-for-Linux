import contextlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import shlex
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import resolve_aac_native as native
import resolve_aac_update as update


def state(active=False, verified=True):
    return dict(import_active=active, import_patched=active, export_installed=active,
                status_verified=verified)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.object(native, "DATA_DIR", self.root))
        self.stack.enter_context(patch.object(native, "RESOLVE_ROOT", self.root / "resolve"))
        self.closed = self.stack.enter_context(patch.object(native, "require_closed"))
        self.status = self.stack.enter_context(patch.object(native, "native_status",
            side_effect=[state(True), state(True), state(), state(True)]))
        self.prepare = self.stack.enter_context(patch.object(native, "prepare_package"))
        self.stack.enter_context(patch.object(native.shutil, "which", return_value="/tool"))
        self.info = self.stack.enter_context(patch.object(native, "resolve_info", return_value=("21.2.0", "studio")))
        self.stack.enter_context(patch.object(native, "source_dir", return_value=self.root))
        self.events = []
        self.remove = self.stack.enter_context(patch.object(native, "uninstall", side_effect=lambda: self.events.append("remove")))
        self.install = self.stack.enter_context(patch.object(native, "install", side_effect=lambda: self.events.append("patch")))
        self.run = self.stack.enter_context(patch.object(native, "run", side_effect=lambda _: self.events.append("installer")))

    def execute(self, **kwargs):
        return update.run_update(self.root / "Resolve installer.run", kwargs.pop("version", "21.2"),
                                 kwargs.pop("edition", "studio"), assume_yes=kwargs.pop("assume_yes", True), **kwargs)

    def journal(self):
        return json.loads((self.root / "update-state.json").read_text())

    def test_remove_install_verify_reapply_in_order(self):
        self.assertEqual(self.execute(), 0)
        self.assertEqual(self.events, ["remove", "installer", "patch"])
        self.assertEqual(self.journal()["phase"], "complete")
        command = self.run.call_args.args[0]
        self.assertEqual(command[:2], ["sudo", "bash"])
        self.assertEqual(command[-3:], ["run-installer", self.root / "Resolve installer.run", "1"])

    def test_legacy_update_does_not_enable_native(self):
        self.status.side_effect = None
        self.status.return_value = state()
        self.assertEqual(self.execute(skip_package_check=False), 0)
        self.assertEqual(self.events, ["installer"])
        self.assertEqual(self.run.call_args.args[0][-1], "0")
        self.prepare.assert_not_called()

    def test_cancel_changes_nothing_and_returns_shell_handoff_code(self):
        with patch("builtins.input", return_value="n"):
            self.assertEqual(self.execute(assume_yes=False), 20)
        self.assertEqual(self.events, [])
        self.assertFalse((self.root / "update-state.json").exists())

    def test_running_resolve_blocks_all_changes(self):
        self.closed.side_effect = RuntimeError("Close Resolve")
        with self.assertRaisesRegex(RuntimeError, "Close Resolve"):
            self.execute()
        self.assertEqual(self.events, [])

    def test_resolve_reopened_before_installer_blocks_it(self):
        self.closed.side_effect = [None, None, RuntimeError("Close Resolve")]
        with self.assertRaisesRegex(RuntimeError, "Close Resolve"):
            self.execute()
        self.assertEqual(self.events, ["remove"])
        self.assertEqual(self.journal()["phase"], "incomplete")

    def test_unknown_status_blocks_installer(self):
        self.status.side_effect = None
        self.status.return_value = state(True, False)
        with self.assertRaisesRegex(RuntimeError, "Cannot verify"):
            self.execute()
        self.prepare.assert_called_once()
        self.assertEqual(self.events, [])

    def test_backup_artifacts_trigger_removal_even_when_status_says_inactive(self):
        self.status.side_effect = [state(), state(), state(), state(True)]
        with patch.object(update, "patch_artifacts", side_effect=[True, False]):
            self.execute()
        self.assertEqual(self.events, ["remove", "installer", "patch"])

    def test_failed_removal_blocks_installer(self):
        self.remove.side_effect = RuntimeError("backup mismatch")
        with self.assertRaisesRegex(RuntimeError, "backup mismatch"):
            self.execute()
        self.run.assert_not_called()
        self.install.assert_not_called()
        self.assertEqual(self.journal()["phase"], "incomplete")

    def test_partial_removal_or_remaining_backups_block_installer(self):
        for leftover in ("binary", "export", "backup"):
            with self.subTest(leftover=leftover):
                clean = state()
                clean["import_patched"] = leftover == "binary"
                clean["export_installed"] = leftover == "export"
                self.status.side_effect = [state(True), state(True), clean]
                with patch.object(update, "patch_artifacts", side_effect=[True, leftover == "backup"]):
                    with self.assertRaisesRegex(RuntimeError, "remain"):
                        self.execute()
                self.run.assert_not_called()

    def test_failed_installer_never_reapplies_or_restores_old_files(self):
        self.run.side_effect = subprocess.CalledProcessError(1, "installer")
        with self.assertRaises(subprocess.CalledProcessError):
            self.execute()
        self.remove.assert_called_once()
        self.install.assert_not_called()
        self.assertEqual(self.journal()["phase"], "incomplete")

    def test_cancelled_installer_with_success_exit_but_old_version_is_detected(self):
        self.info.return_value = ("21.1.0", "studio")
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            self.execute()
        self.install.assert_not_called()

    def test_wrong_edition_is_not_patched(self):
        self.info.return_value = ("21.2.0", "free")
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            self.execute()
        self.install.assert_not_called()

    def test_unsupported_target_is_removed_but_not_patched(self):
        self.info.return_value = ("22.0.0", "studio")
        self.assertEqual(self.execute(version="22"), 0)
        self.assertEqual(self.events, ["remove", "installer"])
        self.assertEqual(self.journal()["phase"], "unsupported")

    def test_build_tools_missing_blocks_update_before_removal(self):
        with patch.object(native.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "build tools"):
                self.execute()
        self.assertEqual(self.events, [])

    def test_repatch_failure_is_persisted_without_rollback(self):
        self.install.side_effect = RuntimeError("unsupported binary pattern")
        with self.assertRaisesRegex(RuntimeError, "unsupported binary pattern"):
            self.execute()
        self.remove.assert_called_once()
        self.assertIn("unsupported binary pattern", self.journal()["message"])
        self.assertEqual(self.journal()["phase"], "incomplete")

    def test_repatch_must_verify_both_components(self):
        partial = state(True)
        partial["export_installed"] = False
        self.status.side_effect = [state(True), state(True), state(), partial]
        with self.assertRaisesRegex(RuntimeError, "verification failed"):
            self.execute()
        self.assertEqual(self.journal()["phase"], "incomplete")

    def test_same_lock_excludes_patch_and_update_and_releases_after_failure(self):
        with self.assertRaisesRegex(RuntimeError, "failure"):
            with native.operation_lock():
                self.assertTrue(native.operation_in_progress())
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    with native.operation_lock():
                        self.fail("Concurrent operation entered")
                raise RuntimeError("failure")
        self.assertFalse(native.operation_in_progress())

    def test_interrupt_waits_until_current_changes_finish(self):
        original = signal.getsignal(signal.SIGTERM)
        with self.assertRaises(KeyboardInterrupt):
            with update.wait_for_changes():
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
                self.events.append("child finished")
        self.assertEqual(self.events, ["child finished"])
        self.assertEqual(signal.getsignal(signal.SIGTERM), original)

    def test_tray_cannot_launch_resolve_during_update(self):
        import resolve_aac_tray as tray
        helper = SimpleNamespace(error=Mock(), resolve_is_running=Mock())
        with native.operation_lock():
            tray.ResolveAacTray.start_resolve(helper)
        helper.error.assert_called_once()
        helper.resolve_is_running.assert_not_called()


class UpdateStatusTests(unittest.TestCase):
    def test_interrupted_update_remains_visible_in_native_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "update-state.json").write_text(json.dumps({"phase": "incomplete", "message": "Installer cancelled."}))
            with patch.object(native, "DATA_DIR", root), patch.object(native, "resolve_info", return_value=("21.2.0", "studio")), \
                 patch.object(native, "find_package", return_value=None):
                status = native.native_status(root)
            self.assertIn("Installer cancelled.", status["details"])
            self.assertEqual(status["update_message"], "Installer cancelled.")


class UpdaterShellTests(unittest.TestCase):
    def test_privileged_installer_refuses_leftover_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = Path(__file__).resolve().parents[1] / "native-aac/privileged.sh"
            helper = root / "helper.sh"
            helper.write_text(source.read_text().replace("root=/opt/resolve", "root=" + shlex.quote(str(root))))
            installer = root / "installer.run"
            installer.write_text("#!/bin/sh\nprintf '%s' \"${SKIP_PACKAGE_CHECK:-strict}\" > \"$(dirname \"$0\")/ran\"\n")
            installer.chmod(0o755)
            (root / "bin").mkdir()
            backup = root / "bin/resolve.aac-orig"
            backup.touch()
            command = ["bash", str(helper), "run-installer", str(installer), "1"]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / "ran").exists())
            backup.unlink()
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual((root / "ran").read_text(), "1")
            command[-1] = "0"
            self.assertEqual(subprocess.run(command, env=dict(os.environ, SKIP_PACKAGE_CHECK="1"), capture_output=True).returncode, 0)
            self.assertEqual((root / "ran").read_text(), "strict")

    def test_shell_delegates_and_skips_launcher_on_cancel_or_failure(self):
        script = Path(__file__).resolve().parents[1] / "scripts/resolve_update_from_downloads.sh"
        with tempfile.TemporaryDirectory(prefix="resolve update test ") as directory:
            root = Path(directory)
            (root / "bin").mkdir()
            for name in ("sudo", "python3"):
                fake = root / "bin" / name
                fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$HOME/arguments\"\nexit \"$TEST_RESULT\"\n")
                fake.chmod(0o755)
            archive = root / "DaVinci_Resolve_Studio_21.2_Linux.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("installer.run", "#!/bin/sh\nexit 99\n")
            for code, expected in ((20, 0), (1, 1)):
                env = dict(os.environ, HOME=str(root), PATH=str(root / "bin") + ":" + os.environ["PATH"], TEST_RESULT=str(code))
                result = subprocess.run(["bash", str(script), "--zip", str(archive), "--tmp-dir", str(root), "--yes"],
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertIn("resolve_aac_update.py", (root / "arguments").read_text())
                self.assertIn("--edition\nstudio\n", (root / "arguments").read_text())
                self.assertFalse((root / ".local/bin/resolve-with-fonts").exists())


if __name__ == "__main__":
    unittest.main()
