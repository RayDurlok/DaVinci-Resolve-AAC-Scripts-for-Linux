#!/usr/bin/env python3
"""Run the official Resolve installer between verified native AAC removal/setup."""

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import sys

import resolve_aac_native as native


def record(phase, message):
    native.DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = native.DATA_DIR / "update-state.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"phase": phase, "message": message}) + "\n")
    temporary.replace(path)
    print(message, flush=True)


def patch_artifacts():
    root = native.RESOLVE_ROOT
    return any(path.exists() for path in (
        root / "bin/resolve.aac-orig", root / "bin/.resolve.aac-orig.sha256",
        root / "libs/_bmd_orig", root / "IOPlugins" / native.PLUGIN_BUNDLE,
    ))


def checked_status():
    state = native.native_status()
    if not state["status_verified"]:
        native.prepare_package()
        state = native.native_status()
    if not state["status_verified"]:
        raise RuntimeError("Cannot verify native AAC status. Refusing further changes; inspect the diagnostics.")
    return state


def version_matches(actual, expected):
    def parts(value):
        result = [int(part) for part in value.split(".")]
        while len(result) < 3:
            result.append(0)
        return result
    return bool(actual) and parts(actual) == parts(expected)


@contextmanager
def wait_for_changes():
    """Don't release the operation lock while a privileged child is still writing."""
    cancelled = False
    def interrupt(_signum, _frame):
        nonlocal cancelled
        cancelled = True
        print("Cancellation requested. Waiting for the current operation to finish; "
              "close/cancel the official installer if it is still open.", flush=True)
    previous = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if cancelled:
            raise KeyboardInterrupt()


def run_update(installer, version, edition, skip_package_check=True, assume_yes=False):
    native.require_closed()
    state = native.native_status()
    artifacts = patch_artifacts()
    has_native = artifacts or state["import_active"] or state["import_patched"] or state["export_installed"]
    if has_native:
        state = checked_status()
    reapply = has_native
    target_supported = native.supported(version, edition)
    if reapply and target_supported:
        missing = [tool for tool in native.BUILD_TOOLS if not native.shutil.which(tool)]
        if missing:
            raise RuntimeError("Install missing native AAC build tools before updating: " + ", ".join(missing))

    print("Close Resolve and keep it closed until the entire update finishes.", flush=True)
    if reapply:
        print("Native AAC: remove import + export support, run the official installer, then verify the installed version.", flush=True)
        print("Native AAC will be reapplied automatically." if target_supported else
              "WARNING: This release is not supported by Native AAC. It will remain disabled; use Legacy if needed.", flush=True)
    else:
        print("Native AAC is not installed; this update will not enable it.", flush=True)
    if not assume_yes and input("Continue with this update? [y/N] ").strip().lower() not in ("y", "yes"):
        print("Cancelled. Nothing changed.", flush=True)
        return 20  # Private handoff code: shell must skip launcher refresh on cancellation.

    try:
        native.require_closed()
        if has_native:
            record("removing", "Step 1/3: Restoring original Resolve files and disabling the native export plugin...")
            with wait_for_changes():
                native.uninstall()
            clean = checked_status()
            if clean["import_active"] or clean["import_patched"] or clean["export_installed"] or patch_artifacts():
                raise RuntimeError("Native AAC files/backups remain. Refusing to start the Resolve installer.")

        native.require_closed()
        record("installing", "Step 2/3: Running the official Resolve installer. Administrator approval may be required...")
        # The privileged helper checks again after sudo authentication, before running the installer.
        with wait_for_changes():
            native.run(["sudo", "bash", native.source_dir() / "privileged.sh", "run-installer",
                        installer, "1" if skip_package_check else "0"])
        native.require_closed()
        installed_version, installed_edition = native.resolve_info()
        if not version_matches(installed_version, version) or installed_edition != edition:
            raise RuntimeError("The installed Resolve version/edition does not match the selected ZIP. "
                               "The installer may have been cancelled. Native AAC was not reapplied.")

        if not reapply:
            record("complete", "Resolve update verified. Native AAC was left unchanged (not installed).")
            return 0
        if not native.supported(installed_version, installed_edition):
            record("unsupported", "Resolve updated, but this version is not supported by Native AAC. "
                   "The patch remains disabled. Open Settings to choose Legacy; no conversion workflow was enabled automatically.")
            return 0
        record("patching", "Step 3/3: Rebuilding and activating native AAC import + export for the updated Resolve...")
        with wait_for_changes():
            native.install()
        final = checked_status()
        if not final["import_active"] or not final["export_installed"]:
            raise RuntimeError("Native AAC verification failed after the update.")
        record("complete", "Resolve update and native AAC import + export verified. You can start Resolve now.")
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        record("incomplete", "Update did not complete: " + (str(exc) or "interrupted") +
               ". Native AAC may be disabled or incomplete. Keep Resolve closed, open Native AAC settings, "
               "refresh the status and repair/disable it before continuing. Never restore backups from an older Resolve build.")
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--edition", required=True, choices=("studio", "free"))
    parser.add_argument("--strict-package-check", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise RuntimeError("Run the updater as your normal user, not with sudo. It requests privileges only when needed.")
    if not args.installer.is_file() or args.installer.suffix != ".run":
        raise RuntimeError("The extracted Resolve .run installer is missing.")
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    with native.operation_lock():
        return run_update(args.installer.resolve(), args.version, args.edition,
                          not args.strict_package_check, args.yes)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Exception, KeyboardInterrupt) as exc:
        print("Resolve updater: " + (str(exc) or "Interrupted. Check native AAC status before starting Resolve."),
              file=sys.stderr, flush=True)
        raise SystemExit(1)
