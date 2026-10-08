import contextlib
import io
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import resolve_aac_installer as installer
import resolve_aac_update as update


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.archive = self.root / "DaVinci_Resolve_Studio_21.2_Linux.zip"
        self.tmp = self.root / "temporary files"
        self.name = "DaVinci_Resolve_Studio_21.2_Linux.run"
        self.payload = b"#!/bin/sh\nexit 99\n"
        self.write_archive()

    def write_archive(self, names=None):
        with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for name in names or [self.name]:
                output.writestr(name, self.payload)
            output.writestr("Linux_Installation_Instructions.html", "instructions")

    def candidate(self, folder, payload=None):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / self.name
        path.write_bytes(self.payload if payload is None else payload)
        return path

    def prepare(self):
        return installer.prepare_installer(self.archive, "21.2", self.tmp)

    def test_fresh_extraction_and_success_cleanup(self):
        prepared = self.prepare()
        self.assertEqual(prepared.path.read_bytes(), self.payload)
        self.assertTrue(os.access(prepared.path, os.X_OK))
        self.assertTrue(prepared.managed)
        self.assertEqual(len(list(prepared.path.parent.iterdir())), 2)
        prepared.cleanup()
        self.assertFalse(prepared.path.parent.exists())
        self.assertTrue(self.archive.exists())

    def test_reuse_beside_zip_preserves_manual_files(self):
        candidate = self.candidate(self.root)
        prepared = self.prepare()
        self.assertEqual(prepared.path, candidate)
        self.assertFalse(prepared.managed)
        prepared.cleanup()
        self.assertTrue(candidate.exists())
        self.assertFalse(self.tmp.exists())

    def test_reuse_zip_named_subfolder(self):
        candidate = self.candidate(self.archive.with_suffix(""))
        prepared = self.prepare()
        self.assertEqual(prepared.path, candidate)
        self.assertFalse(prepared.managed)

    def test_reuse_old_temporary_extraction_without_deleting_it(self):
        candidate = self.candidate(self.tmp / "resolve-21.2.OLD")
        prepared = self.prepare()
        self.assertEqual(prepared.path, candidate)
        prepared.cleanup()
        self.assertTrue(candidate.exists())

    def test_reuse_managed_retry_then_cleanup(self):
        first = self.prepare()
        retry = self.prepare()
        self.assertEqual(first.path, retry.path)
        self.assertTrue(retry.managed)
        retry.cleanup()
        self.assertFalse(first.path.parent.exists())

    def test_changed_same_size_candidate_is_not_used(self):
        candidate = self.candidate(self.root, self.payload.replace(b"99", b"00"))
        prepared = self.prepare()
        self.assertNotEqual(prepared.path, candidate)
        self.assertEqual(candidate.read_bytes(), self.payload.replace(b"99", b"00"))

    def test_truncated_candidate_is_not_used(self):
        candidate = self.candidate(self.root, b"partial")
        self.assertNotEqual(self.prepare().path, candidate)

    def test_changed_zip_does_not_reuse_previous_installer(self):
        first = self.prepare()
        self.payload = self.payload.replace(b"99", b"00")
        self.write_archive()
        second = self.prepare()
        self.assertNotEqual(first.path, second.path)
        self.assertTrue(first.path.exists())

    def test_symlink_candidate_is_ignored(self):
        original = self.root / "manual.run"
        original.write_bytes(self.payload)
        candidate = self.root / self.name
        candidate.symlink_to(original)
        self.assertNotEqual(self.prepare().path, candidate)

    def test_symlink_folder_is_ignored(self):
        folder = self.root / "manual"
        self.candidate(folder)
        self.archive.with_suffix("").symlink_to(folder, target_is_directory=True)
        self.assertTrue(self.prepare().managed)

    def test_cleanup_keeps_unexpected_files(self):
        prepared = self.prepare()
        extra = prepared.path.parent / "keep.txt"
        extra.write_text("user data")
        prepared.cleanup()
        self.assertTrue(extra.exists())
        self.assertTrue(prepared.path.exists())

    def test_missing_marker_prevents_cleanup(self):
        prepared = self.prepare()
        (prepared.path.parent / installer.MARKER).unlink()
        prepared.cleanup()
        self.assertTrue(prepared.path.exists())

    def test_reject_unsafe_or_ambiguous_archive(self):
        for names in (["../installer.run"], ["/installer.run"], ["folder/installer.run"],
                      ["a.run", "b.run"], ["readme.txt"]):
            with self.subTest(names=names):
                self.write_archive(names)
                with self.assertRaises(RuntimeError):
                    self.prepare()
        self.assertFalse(self.tmp.exists())

    def test_reject_archive_symlink(self):
        entry = zipfile.ZipInfo(self.name)
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(self.archive, "w") as output:
            output.writestr(entry, "somewhere")
        with self.assertRaises(RuntimeError):
            self.prepare()

    def test_failed_extraction_removes_partial_directory(self):
        with patch.object(installer.shutil, "copyfileobj", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.prepare()
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_interrupted_extraction_removes_partial_directory(self):
        with patch.object(installer.shutil, "copyfileobj", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.prepare()
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_running_resolve_blocks_preparation(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, "argv", ["updater", "--zip", str(self.archive),
                "--version", "21.2", "--edition", "studio", "--yes"]))
            stack.enter_context(patch.object(update.os, "geteuid", return_value=1000))
            stack.enter_context(patch.object(update.signal, "signal"))
            stack.enter_context(patch.object(update.native, "operation_lock", contextlib.nullcontext))
            stack.enter_context(patch.object(update.native, "require_closed", side_effect=RuntimeError("Close Resolve")))
            prepare = stack.enter_context(patch.object(update, "prepare_installer"))
            with self.assertRaisesRegex(RuntimeError, "Close Resolve"):
                update.main()
            prepare.assert_not_called()

    def test_corrupt_zip_never_reuses_candidate(self):
        self.candidate(self.root)
        with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_STORED) as output:
            output.writestr(self.name, self.payload)
        content = self.archive.read_bytes()
        self.archive.write_bytes(content.replace(self.payload, self.payload.replace(b"99", b"00")))
        with self.assertRaises(zipfile.BadZipFile):
            self.prepare()

    def test_main_prepares_inside_lock_and_cleans_only_on_success(self):
        for result in (0, 20, RuntimeError("installer failed")):
            with self.subTest(result=result), contextlib.ExitStack() as stack:
                events = []

                @contextlib.contextmanager
                def lock():
                    events.append("lock")
                    yield
                    events.append("unlock")

                prepared = installer.PreparedInstaller(self.root / self.name, True)
                def prepare(*args):
                    events.append("prepare")
                    return prepared

                stack.enter_context(patch.object(sys, "argv", ["updater", "--zip", str(self.archive),
                    "--version", "21.2", "--edition", "studio", "--yes"]))
                stack.enter_context(patch.object(update.os, "geteuid", return_value=1000))
                stack.enter_context(patch.object(update.signal, "signal"))
                stack.enter_context(patch.object(update.native, "operation_lock", lock))
                stack.enter_context(patch.object(update.native, "require_closed",
                                                 side_effect=lambda: events.append("closed")))
                stack.enter_context(patch.object(update, "prepare_installer", side_effect=prepare))
                run = stack.enter_context(patch.object(update, "run_update"))
                if isinstance(result, Exception):
                    run.side_effect = result
                else:
                    run.return_value = result
                cleanup = stack.enter_context(patch.object(prepared, "cleanup"))
                if isinstance(result, Exception):
                    with self.assertRaises(RuntimeError):
                        update.main()
                else:
                    self.assertEqual(update.main(), result)
                self.assertEqual(events[:3], ["lock", "closed", "prepare"])
                self.assertEqual(cleanup.call_count, int(result == 0))


if __name__ == "__main__":
    unittest.main()
