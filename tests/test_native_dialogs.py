import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import resolve_aac_dialogs as dialogs
import resolve_aac_tray as tray
import set_render_location as render


class LaunchTests(unittest.TestCase):
    def test_disabled_setting_does_not_build_or_enable_inherited_flag(self):
        with patch.object(dialogs, "enabled", return_value=False), patch.object(dialogs, "prepare_library") as build:
            result = dialogs.launch_environment({"RESOLVE_TOOLKIT_NATIVE_DIALOGS": "1", "LD_PRELOAD": "user.so"})
        build.assert_not_called()
        self.assertNotIn("RESOLVE_TOOLKIT_NATIVE_DIALOGS", result)
        self.assertEqual(result["LD_PRELOAD"], "user.so")

    def test_enabled_retains_existing_preload_and_sets_helper(self):
        with patch.object(dialogs, "enabled", return_value=True), patch.object(dialogs, "prepare_library", return_value=Path("/tmp/test.so")):
            result = dialogs.launch_environment({"LD_PRELOAD": "glib.so"})
        self.assertEqual(result["LD_PRELOAD"], "glib.so /tmp/test.so")
        self.assertEqual(result["RESOLVE_TOOLKIT_NATIVE_DIALOGS"], "1")
        self.assertEqual(result["RESOLVE_NATIVE_DELIVER_PYTHON"], sys.executable)
        self.assertEqual(result["RESOLVE_NATIVE_DELIVER_HELPER"], str(Path(dialogs.__file__).resolve()))

    def test_build_failure_preserves_launch_fallback(self):
        with patch.object(dialogs, "enabled", return_value=True), patch.object(dialogs, "prepare_library", side_effect=RuntimeError("missing headers")), patch("builtins.print"):
            result = dialogs.launch_environment({"LD_PRELOAD": "user.so"})
        self.assertEqual(result, {"LD_PRELOAD": "user.so"})

    def test_helper_environment_does_not_leak_resolve_libraries(self):
        names = ("LD_PRELOAD", "LD_LIBRARY_PATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORMTHEME", "PYTHONHOME", "PYTHONPATH")
        result = dialogs.clean_helper_env(dict.fromkeys(names, "bad") | {"DISPLAY": ":0"})
        self.assertEqual(result, {"DISPLAY": ":0"})

    def test_font_wrapper_uses_shared_launcher_and_quotes_spaces(self):
        with patch.object(tray, "SCRIPT_DIR", Path("/tmp/toolkit path")):
            text = tray.ResolveAacTray.resolve_font_wrapper_content(None)
        self.assertIn("exec bash '/tmp/toolkit path/resolve-with-fonts.sh'", text)
        self.assertIn('"$@"', text)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        for name in dialogs.SOURCES:
            (self.source / name).write_text("// source\n")
        self.resolve = self.root / "resolve/bin/resolve"
        self.libs = self.root / "resolve/libs"
        self.libs.mkdir(parents=True)
        for name in dialogs.LIBRARIES:
            (self.libs / name).write_bytes(b"library")
        self.cache = self.root / "cache"
        self.find_source = dialogs.source_dir
        for name, value in (("source_dir", self.source), ("cache_dir", self.cache)):
            p = patch.object(dialogs, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        for name, value in (("system", "Linux"), ("machine", "x86_64")):
            p = patch.object(dialogs.platform, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def test_build_cached_and_source_change_invalidates(self):
        def compile_library(command, **kwargs):
            Path(command[-1]).write_bytes(b"compiled")
        with patch.object(dialogs, "build_tools", return_value=("c++", ["-I/qt"])) as deps, patch.object(dialogs.subprocess, "run", side_effect=compile_library) as run:
            first = dialogs.prepare_library(self.resolve)
            self.assertEqual(first.read_bytes(), b"compiled")
            self.assertEqual(dialogs.prepare_library(self.resolve), first)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(deps.call_count, 1)
            (self.source / "relink_bridge.cpp").write_text("// changed\n")
            self.assertNotEqual(dialogs.prepare_library(self.resolve), first)
            self.assertEqual(run.call_count, 2)
        self.assertEqual(list(self.cache.glob("build-*.so")), [])

    def test_failed_build_never_leaves_loadable_cache(self):
        with patch.object(dialogs, "build_tools", return_value=("c++", [])), patch.object(dialogs.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "c++")):
            with self.assertRaises(subprocess.CalledProcessError):
                dialogs.prepare_library(self.resolve)
        self.assertEqual(list(self.cache.glob("*.so")), [])

    def test_repo_and_flat_package_sources_are_found(self):
        with patch.object(dialogs, "SCRIPT_DIR", self.root / "scripts"):
            (self.root / "native-dialogs").mkdir()
            for name in dialogs.SOURCES:
                (self.root / "native-dialogs" / name).touch()
            source = self.root / "native-dialogs"
            self.assertEqual(self.find_source(), source)
        with patch.object(dialogs, "SCRIPT_DIR", self.root):
            self.assertEqual(self.find_source(), source)


class PickerTests(unittest.TestCase):
    def test_picker_reuses_existing_history_and_mute_aware_entrypoint(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(dialogs, "cache_dir", return_value=Path(directory)), patch.object(render, "main", return_value=0) as main:
            self.assertEqual(dialogs.deliver_picker(), 0)
            main.assert_called_once_with([])

    def test_picker_duplicate_returns_without_another_dialog(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(dialogs, "cache_dir", return_value=Path(directory)), patch.object(dialogs.fcntl, "flock", side_effect=BlockingIOError), patch.object(render, "main") as main:
            self.assertEqual(dialogs.deliver_picker(), 0)
            main.assert_not_called()

    def test_picker_error_is_visible(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(dialogs, "cache_dir", return_value=Path(directory)), patch.object(render, "main", side_effect=RuntimeError("failed")), patch.object(render, "notify") as notify:
            self.assertEqual(dialogs.deliver_picker(), 1)
            notify.assert_called_once_with("Could not set the render destination: failed", critical=True)


if __name__ == "__main__":
    unittest.main()
