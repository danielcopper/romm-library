"""Centralized RetroDECK path resolution.

Reads paths from retrodeck.json config, with fallback to ~/retrodeck/{subdir}.
Uses a 30-second TTL cache to avoid re-reading disk on every call during
batch operations (e.g. 50-ROM save sync).
"""

import json
import os
import time

_CACHE_TTL = 30  # seconds

_cached_config = None
_cache_time = 0.0
_cache_config_path = None

# Module-level configuration — set via configure() during bootstrap.
# Falls back to importing decky lazily if not configured (dev/test fallback).
_user_home = None


def configure(user_home: str) -> None:
    """Configure the user home path used for RetroDECK path resolution.

    Must be called once during bootstrap before any path resolution functions
    are used.
    """
    global _user_home
    _user_home = user_home


def _get_user_home() -> str:
    """Return the configured user home, raising if not configured."""
    if _user_home is not None:
        return _user_home
    raise RuntimeError("retrodeck_config not configured — call configure() during bootstrap")


def _config_path():
    """Return the path to retrodeck.json, using current user home."""
    return os.path.join(
        _get_user_home(),
        ".var",
        "app",
        "net.retrodeck.retrodeck",
        "config",
        "retrodeck",
        "retrodeck.json",
    )


def _load_config():
    """Load retrodeck.json with TTL caching."""
    global _cached_config, _cache_time, _cache_config_path
    config_path = _config_path()
    now = time.monotonic()
    if _cached_config is not None and _cache_config_path == config_path and (now - _cache_time) < _CACHE_TTL:
        return _cached_config
    try:
        with open(config_path) as f:
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
    return os.path.join(_get_user_home(), "retrodeck", fallback_subdir)


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
