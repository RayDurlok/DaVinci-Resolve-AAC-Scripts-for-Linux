#!/usr/bin/env python3

from pathlib import Path


STOP_PATH = Path("/tmp/resolve_aac_mediapool_watch.stop")
STOP_PATH.touch()
print(f"Requested Resolve AAC MediaPool watcher stop: {STOP_PATH}")
