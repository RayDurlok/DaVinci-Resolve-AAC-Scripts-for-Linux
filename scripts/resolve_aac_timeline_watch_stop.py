#!/usr/bin/env python3

from pathlib import Path


STOP_PATH = Path("/tmp/resolve_aac_timeline_watch.stop")
STOP_PATH.touch()
print(f"Requested Resolve AAC timeline watcher stop: {STOP_PATH}")
