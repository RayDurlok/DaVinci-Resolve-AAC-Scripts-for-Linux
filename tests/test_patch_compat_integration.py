"""Optional checks using a prepared upstream package, without proprietary fixtures.

Set RESOLVE_AACFIX_TEST_PACKAGE to a temporary package with the overlay applied.
The ordinary test suite needs neither capstone nor downloaded patch binaries.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PACKAGE = os.environ.get("RESOLVE_AACFIX_TEST_PACKAGE")


class CodeMap:
    def __init__(self, data):
        self.data = data

    def exec_ranges(self):
        return [(0, len(self.data), 0x1000)]

    def off_to_va(self, offset):
        return offset + 0x1000


@unittest.skipUnless(PACKAGE, "Set RESOLVE_AACFIX_TEST_PACKAGE for real upstream integration checks")
class UpstreamCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path[:0] = [PACKAGE, str(Path(PACKAGE) / "vendor/pylibs")]
        from aacpatch.sites import SIGNATURES
        cls.gate = next(sig for sig in SIGNATURES if sig.name == "gate1_dispatch")

    def test_real_decoder_accepts_only_inspected_registers(self):
        for modrm in (0xff, 0xfc, 0xfd, 0xfe, 0xfb):
            code = bytes([0x41, 0x81, modrm]) + bytes.fromhex("33 70 6d 2e 0f 84 01 00 00 00")
            with self.subTest(modrm=modrm):
                if modrm in (0xff, 0xfc):
                    self.assertEqual(self.gate.locate(code, CodeMap(code)), 0)
                else:
                    with self.assertRaisesRegex(LookupError, "verification"):
                        self.gate.locate(code, CodeMap(code))

    def test_ambiguous_sites_still_refuse(self):
        code = bytes.fromhex("41 81 fc 33 70 6d 2e 0f 84 01 00 00 00") * 2
        with self.assertRaisesRegex(LookupError, "ambiguous"):
            self.gate.locate(code, CodeMap(code))

    def test_wrong_branch_still_refuses(self):
        code = bytes.fromhex("41 81 fc 33 70 6d 2e 0f 85 01 00 00 00")
        with self.assertRaisesRegex(LookupError, "not found"):
            self.gate.locate(code, CodeMap(code))

    def test_unknown_binary_produces_no_patched_output(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "output"
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                       PYTHONPATH=os.pathsep.join([PACKAGE, str(Path(PACKAGE) / "vendor/pylibs")]),
                       AAC_TRAMPOLINE=str(Path(directory) / "must-not-be-used"))
            result = subprocess.run([sys.executable, "-m", "aacpatch.additive", "/bin/true", "-o", str(target)],
                                    env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("no output written", result.stdout)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
