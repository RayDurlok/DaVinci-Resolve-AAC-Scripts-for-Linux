#!/usr/bin/env python3

import json
from pathlib import Path

# Keep in sync with the RPM spec Version (packaging/rpm/resolve-aac-tools.spec).
APP_VERSION = "0.2.1"

CONFIG_DIR = Path.home() / ".config" / "resolve-aac-tools"
CONFIG_PATH = CONFIG_DIR / "config.json"
START_REQUEST_PATH = CONFIG_DIR / "start_resolve.request"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "resolve-aac-remux"

DEFAULT_CONFIG = {
    "use_cache": False,
    "cache_dir": str(DEFAULT_CACHE_DIR),
    "watch_manual_resolve": True,
    "remux_exports": False,
    "intercept_deliver_browse": False,
    "mute_notifications": False,
    "logging_enabled": True,
    "window_width": 880,
    "window_height": 600,
    "setup_completed": False,
}


def load_config():
    config = dict(DEFAULT_CONFIG)
    try:
        data = json.loads(CONFIG_PATH.read_text())
    except Exception:
        return config

    config.update({key: data[key] for key in config if key in data})
    if "remux_exports" not in data and "web_export_watch" in data:
        config["remux_exports"] = bool(data["web_export_watch"])
    return config


def save_config(config):
    merged = dict(DEFAULT_CONFIG)
    merged.update({key: config[key] for key in config if key in merged})
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(merged, indent=2) + "\n")
    return merged


def should_show_setup(config=None):
    if not CONFIG_PATH.exists():
        return True
    config = load_config() if config is None else config
    return not bool(config.get("setup_completed", False))
