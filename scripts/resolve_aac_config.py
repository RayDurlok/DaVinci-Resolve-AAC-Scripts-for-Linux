#!/usr/bin/env python3

import json
from pathlib import Path

# Keep in sync with the RPM spec Version (packaging/rpm/resolve-aac-tools.spec).
APP_VERSION = "0.3.0"
NATIVE_AAC_NOTICE_VERSION = 1

CONFIG_DIR = Path.home() / ".config" / "resolve-aac-tools"
CONFIG_PATH = CONFIG_DIR / "config.json"
START_REQUEST_PATH = CONFIG_DIR / "start_resolve.request"
SETTINGS_REQUEST_PATH = CONFIG_DIR / "open_settings.request"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "resolve-aac-remux"
LEGACY_STOP_PATHS = tuple(Path("/tmp") / name for name in (
    "resolve_aac_mediapool_watch.stop", "resolve_aac_timeline_watch.stop",
    "resolve_aac_export_watch.stop", "resolve_aac_watch.stop",
))

DEFAULT_CONFIG = {
    "aac_mode": "legacy",
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
    "native_aac_notice_version": 0,
}


def load_config():
    config = dict(DEFAULT_CONFIG)
    try:
        data = json.loads(CONFIG_PATH.read_text())
    except Exception:
        return config

    config.update({key: data[key] for key in config if key in data})
    if config["aac_mode"] not in ("native", "legacy"):
        config["aac_mode"] = "legacy"
    if "remux_exports" not in data and "web_export_watch" in data:
        config["remux_exports"] = bool(data["web_export_watch"])
    return config


def save_config(config):
    merged = dict(DEFAULT_CONFIG)
    merged.update({key: config[key] for key in config if key in merged})
    if merged["aac_mode"] not in ("native", "legacy"):
        raise ValueError("Unknown AAC workflow")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(merged, indent=2) + "\n")
    return merged


def should_show_setup(config=None):
    if not CONFIG_PATH.exists():
        return True
    config = load_config() if config is None else config
    return not bool(config.get("setup_completed", False))


def legacy_enabled(config):
    return config.get("aac_mode", "legacy") == "legacy"


def legacy_workflow_active():
    return legacy_enabled(load_config())


def should_show_native_update(config):
    try:
        seen = int(config.get("native_aac_notice_version", 0))
    except (TypeError, ValueError):
        seen = 0
    return bool(config.get("setup_completed")) and seen < NATIVE_AAC_NOTICE_VERSION
