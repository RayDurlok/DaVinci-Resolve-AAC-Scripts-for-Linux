"""Small, source-verified compatibility overlay for resolve-aacfix v0.1.1.

Studio 21.1.1 keeps the QuickTime codec fourcc in r12d instead of r15d.
Both the signature verifier and the trampoline argument must follow that change.
Upstream code remains MIT; no proprietary binary bytes are distributed here.
"""

import hashlib
from pathlib import Path


SOURCE_SHA256 = {
    "aacpatch/sites.py": "b5727ee89b76adffaf76356f8825b2422a89bcf364ebf6c30ca6d3badfee8471",
    "aacpatch/additive.py": "a2f35f33fdea36c086c69e2058898f0ee663cb69474a0234e28fa9dedb6767cf",
}

REPLACEMENTS = {
    "aacpatch/sites.py": (
        ('pattern="41 81 ff 33 70 6d 2e 0f 84 ?? ?? ?? ??",     # cmp \'.mp3\'; je',
         'pattern="41 81 ?? 33 70 6d 2e 0f 84 ?? ?? ?? ??",     # cmp \'.mp3\'; je\n'
         '        # Toolkit: accept only the two inspected register allocations.\n'
         '        verify=lambda cs, off, em, buf: any(\n'
         '            _v_cmp_imm(reg, 0x2e6d7033)(cs, off, em, buf)\n'
         '            for reg in ("r15d", "r12d")),'),
    ),
    "aacpatch/additive.py": (
        ('"g1_site":    va(g1),',
         '"g1_site":    va(g1),\n'
         '        # Signature verification restricts the ModRM byte to these registers.\n'
         '        "g1_reg":     {0xff: 15, 0xfc: 12}[buf[g1 + 2]],'),
        ('R("r15", AAC_FOURCC,   a["g1_target"])',
         'R("r" + str(a["g1_reg"]), AAC_FOURCC, a["g1_target"])'),
    ),
}


def apply_compatibility(package):
    """Adapt only pristine, pinned upstream source, before promoting its cache."""
    package = Path(package)
    changes = {}
    for relative, expected in SOURCE_SHA256.items():
        path = package / relative
        original = path.read_bytes()
        if hashlib.sha256(original).hexdigest() != expected:
            raise RuntimeError("Unexpected upstream patch source; refusing compatibility overlay: " + relative)
        text = original.decode("utf-8")
        for old, new in REPLACEMENTS[relative]:
            if text.count(old) != 1:
                raise RuntimeError("Upstream compatibility anchor is missing or ambiguous: " + relative)
            text = text.replace(old, new, 1)
        compile(text, relative, "exec")
        changes[path] = text
    for path, text in changes.items():
        path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="Freshly extracted, verified v0.1.1 package")
    apply_compatibility(parser.parse_args().package)
