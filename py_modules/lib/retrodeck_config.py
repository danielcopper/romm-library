"""Centralized RetroDECK path resolution.

Reads paths from retrodeck.json config, with fallback to ~/retrodeck/{subdir}.
Uses a 30-second TTL cache to avoid re-reading disk on every call during
batch operations (e.g. 50-ROM save sync).
"""
import json
import os
import time

import decky

_CACHE_TTL = 30  # seconds

_cached_config = None
_cache_time = 0.0
_cache_config_path = None


def _reset_cache():
    """Reset the TTL cache (for testing)."""
    global _cached_config, _cache_time, _cache_config_path
    _cached_config = None
    _cache_time = 0.0
    _cache_config_path = None


def _config_path():
    """Return the path to retrodeck.json, using current DECKY_USER_HOME."""
    return os.path.join(
        decky.DECKY_USER_HOME,
        ".var", "app", "net.retrodeck.retrodeck",
        "config", "retrodeck", "retrodeck.json",
    )


def _load_config():
    """Load retrodeck.json with TTL caching."""
    global _cached_config, _cache_time, _cache_config_path
    config_path = _config_path()
    now = time.monotonic()
    if (_cached_config is not None
            and _cache_config_path == config_path
            and (now - _cache_time) < _CACHE_TTL):
        return _cached_config
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
        _cached_config = config
        _cache_time = now
        _cache_config_path = config_path
        return config
    except (OSError, json.JSONDecodeError):
        _cached_config = None
        _cache_config_path = config_path
        _cache_time = now
        return None


def get_retrodeck_path(key, fallback_subdir):
    """Read a path from retrodeck.json paths.{key}, fallback to ~/retrodeck/{subdir}."""
    config = _load_config()
    if config:
        path = config.get("paths", {}).get(key, "")
        if path:
            return path
    return os.path.join(decky.DECKY_USER_HOME, "retrodeck", fallback_subdir)


def get_bios_path():
    """Return the BIOS directory path from RetroDECK config."""
    return get_retrodeck_path("bios_path", "bios")


def get_roms_path():
    """Return the ROMs directory path from RetroDECK config."""
    return get_retrodeck_path("roms_path", "roms")


def get_saves_path():
    """Return the saves directory path from RetroDECK config."""
    return get_retrodeck_path("saves_path", "saves")


def get_retrodeck_home():
    """Return the RetroDECK home directory path from config."""
    return get_retrodeck_path("rd_home_path", "")
