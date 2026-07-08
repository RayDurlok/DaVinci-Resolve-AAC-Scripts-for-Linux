#!/usr/bin/env python3

from __future__ import print_function

import datetime
import os
import subprocess


SCRIPT_DIR = os.environ.get("RESOLVE_AAC_APP_DIR") or os.path.dirname(os.path.realpath(__file__))
SCRIPT = os.path.join(SCRIPT_DIR, "resolve_aac_timeline.py")
LOG = "/tmp/resolve_aac_current_clip.log"


def find_python3():
    for candidate in ("/usr/bin/python3", "/bin/python3", "python3"):
        if os.path.isabs(candidate) and os.path.exists(candidate):
            return candidate
    return "python3"


def main():
    env = os.environ.copy()
    env.setdefault("RESOLVE_SCRIPT_API", "/opt/resolve/Developer/Scripting")
    env.setdefault("RESOLVE_SCRIPT_LIB", "/opt/resolve/libs/Fusion/fusionscript.so")
    env["PYTHONPATH"] = (
        env.get("PYTHONPATH", "")
        + os.pathsep
        + "/opt/resolve/Developer/Scripting/Modules"
    )

    with open(LOG, "a") as log:
        log.write("\n=== Resolve AAC Current Clip: %s ===\n" % datetime.datetime.now().isoformat())
        log.write("Launching %s\n" % SCRIPT)
        log.flush()
        subprocess.Popen(
            [find_python3(), SCRIPT, "--overwrite"],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=os.path.dirname(SCRIPT),
        )


main()
