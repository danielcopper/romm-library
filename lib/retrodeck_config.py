"""Centralized RetroDECK path resolution.

Reads paths from retrodeck.json config, with fallback to ~/retrodeck/{subdir}.
Each call reads fresh from disk (no caching) to handle config changes.
"""
import json
import os

import decky


def _config_path():
    """Return the path to retrodeck.json, using current DECKY_USER_HOME."""
    return os.path.join(
        decky.DECKY_USER_HOME,
        ".var", "app", "net.retrodeck.retrodeck",
        "config", "retrodeck", "retrodeck.json",
    )


def get_retrodeck_path(key, fallback_subdir):
    """Read a path from retrodeck.json paths.{key}, fallback to ~/retrodeck/{subdir}."""
    try:
        with open(_config_path(), "r") as f:
            config = json.load(f)
        path = config.get("paths", {}).get(key, "")
        if path:
            return path
    except (OSError, json.JSONDecodeError):
        pass
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
