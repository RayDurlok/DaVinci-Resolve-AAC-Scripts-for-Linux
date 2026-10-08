"""Reuse ZIP-matched Resolve installers without deleting manual extractions."""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile


MARKER = ".resolve-toolkit-installer"
CHUNK_SIZE = 1024 * 1024


def digest(stream):
    checksum = hashlib.sha256()
    while chunk := stream.read(CHUNK_SIZE):
        checksum.update(chunk)
    return checksum.digest()


@dataclass
class PreparedInstaller:
    path: Path
    managed: bool = False

    def cleanup(self):
        if not self.managed:
            return
        folder = self.path.parent
        try:
            # Never recursively remove a reused directory or unexpected user files.
            if not managed_folder(folder, self.path.name):
                return
            self.path.unlink()
            (folder / MARKER).unlink()
            folder.rmdir()
            print("Removed temporary installer files.", flush=True)
        except OSError as exc:
            print(f"Could not remove temporary installer files: {exc}", flush=True)


def managed_folder(folder, name):
    marker = folder / MARKER
    try:
        return (not folder.is_symlink() and folder.stat().st_uid == os.getuid()
                and not marker.is_symlink() and marker.is_file()
                and marker.read_text() == f"resolve-toolkit-installer-v1\n{name}\n"
                and {entry.name for entry in folder.iterdir()} == {name, MARKER})
    except (OSError, UnicodeError):
        return False


def prepare_installer(archive, version, tmp_root):
    archive = Path(archive).absolute()
    tmp_root = Path(tmp_root).absolute()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version):
        raise ValueError("Invalid Resolve version.")
    with zipfile.ZipFile(archive) as source:
        installers = [entry for entry in source.infolist() if entry.filename.endswith(".run")]
        if len(installers) != 1:
            raise RuntimeError("Expected exactly one .run installer in the ZIP.")
        entry = installers[0]
        name = entry.filename
        mode = entry.external_attr >> 16
        if (Path(name).name != name or "\\" in name
                or stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
            raise RuntimeError("The ZIP installer must be a regular file at the archive root.")

        folders = [archive.parent, archive.with_suffix("")]
        if tmp_root.is_dir():
            folders.extend(sorted(tmp_root.glob(f"resolve-{version}.*")))
        expected = None
        for folder in folders:
            candidate = folder / name
            try:
                if folder.is_symlink() or not folder.is_dir() or folder.stat().st_uid != os.getuid():
                    continue
                info = candidate.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_size != entry.file_size:
                    continue
                print(f"Checking extracted installer against ZIP: {candidate}", flush=True)
                if expected is None:
                    with source.open(entry) as content:
                        expected = digest(content)
                with candidate.open("rb") as content:
                    matches = digest(content) == expected
                if not matches:
                    print("Extracted installer differs from ZIP; leaving it untouched.", flush=True)
                    continue
                candidate.chmod(stat.S_IMODE(info.st_mode) | stat.S_IXUSR)
                print(f"Reusing verified installer: {candidate}", flush=True)
                managed = folder not in folders[:2] and managed_folder(folder, name)
                return PreparedInstaller(candidate, managed)
            except OSError:
                continue

        tmp_root.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix=f"resolve-{version}.", dir=tmp_root))
        target = folder / name
        print(f"Extracting installer: {target}", flush=True)
        try:
            with source.open(entry) as content, target.open("xb") as output:
                shutil.copyfileobj(content, output, CHUNK_SIZE)
            target.chmod(0o700)
            (folder / MARKER).write_text(f"resolve-toolkit-installer-v1\n{name}\n")
        except BaseException:
            shutil.rmtree(folder)
            raise
        return PreparedInstaller(target, True)
