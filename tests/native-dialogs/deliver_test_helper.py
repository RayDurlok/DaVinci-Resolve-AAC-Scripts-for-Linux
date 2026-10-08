"""No UI/API: record the child environment for the Deliver bridge test."""
import os
from pathlib import Path
import time

names = ("LD_PRELOAD", "LD_LIBRARY_PATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORMTHEME",
         "PYTHONHOME", "PYTHONPATH")
with Path(os.environ["DELIVER_TEST_OUTPUT"]).open("a") as output:
    output.write("clean\n" if all(name not in os.environ for name in names) else "dirty\n")
time.sleep(0.5)
