"""Regression tests for the pinned upstream source overlay, without Resolve files."""

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import resolve_aac_patch_compat as compat


SITES = '''
class Signature:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

def _v_cmp_imm(reg, imm):
    return lambda cs, off, em, buf: cs == (reg, imm)

gate = Signature(
        name="gate1_dispatch",
        pattern="41 81 ff 33 70 6d 2e 0f 84 ?? ?? ?? ??",     # cmp '.mp3'; je
        where="exec",
)
'''

ADDITIVE = '''
def addresses(buf, g1, va):
    return {
        "g1_site":    va(g1),
    }

AAC_FOURCC = 0x61616320

def build(a):
    def R(reg, value, target):
        return (reg, value, target)
    return R("r15", AAC_FOURCC,   a["g1_target"])
'''


class PatchCompatibilityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.package = Path(directory.name)
        (self.package / "aacpatch").mkdir()
        self.sources = {"aacpatch/sites.py": SITES, "aacpatch/additive.py": ADDITIVE}
        self.hashes = {}
        for name, source in self.sources.items():
            (self.package / name).write_text(source)
            self.hashes[name] = hashlib.sha256(source.encode()).hexdigest()
        context = patch.dict(compat.SOURCE_SHA256, self.hashes, clear=True)
        context.start()
        self.addCleanup(context.stop)

    def test_verifier_and_redirect_use_the_same_inspected_register(self):
        compat.apply_compatibility(self.package)
        sites, additive = {}, {}
        exec((self.package / "aacpatch/sites.py").read_text(), sites)
        exec((self.package / "aacpatch/additive.py").read_text(), additive)
        for byte, short, full in ((0xff, "r15d", "r15"), (0xfc, "r12d", "r12")):
            with self.subTest(register=short):
                self.assertTrue(sites["gate"].verify((short, 0x2e6d7033), 0, None, b""))
                addresses = additive["addresses"](bytes((0x41, 0x81, byte)), 0, lambda value: value)
                addresses["g1_target"] = 1234
                self.assertEqual(additive["build"](addresses), (full, 0x61616320, 1234))
        for register in ("r13d", "r14d", "edi", "r12", "r15"):
            self.assertFalse(sites["gate"].verify((register, 0x2e6d7033), 0, None, b""))
        self.assertFalse(sites["gate"].verify(("r12d", 0x61616320), 0, None, b""))
        self.assertEqual(sites["gate"].pattern, "41 81 ?? 33 70 6d 2e 0f 84 ?? ?? ?? ??")

    def test_unknown_upstream_source_refuses_before_any_write(self):
        path = self.package / "aacpatch/additive.py"
        changed = ADDITIVE + "\n# unknown change\n"
        path.write_text(changed)
        with self.assertRaisesRegex(RuntimeError, "Unexpected upstream"):
            compat.apply_compatibility(self.package)
        self.assertEqual(path.read_text(), changed)
        self.assertEqual((self.package / "aacpatch/sites.py").read_text(), SITES)

    def test_source_anchors_must_be_unique(self):
        for source in ("x = 1\n", ADDITIVE + ADDITIVE):
            with self.subTest(source=source):
                (self.package / "aacpatch/additive.py").write_text(source)
                compat.SOURCE_SHA256["aacpatch/additive.py"] = hashlib.sha256(source.encode()).hexdigest()
                with self.assertRaisesRegex(RuntimeError, "missing or ambiguous"):
                    compat.apply_compatibility(self.package)
                self.assertEqual((self.package / "aacpatch/sites.py").read_text(), SITES)

    def test_overlay_cannot_be_applied_twice(self):
        compat.apply_compatibility(self.package)
        with self.assertRaisesRegex(RuntimeError, "Unexpected upstream"):
            compat.apply_compatibility(self.package)


if __name__ == "__main__":
    unittest.main()
