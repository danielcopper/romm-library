"""Pure schema-migration functions for plugin state files.

Each function accepts a raw dict (as loaded from disk) and returns
the same dict promoted to the current schema version.  No I/O —
reading and writing is the caller's responsibility.
"""

from __future__ import annotations


def migrate_settings(data: dict) -> dict:
    """Bring *data* from any older settings schema to the current version."""
    version = data.get("version", 0)
    if version < 1:
        # v0 → v1: rename deprecated boolean keys
        if data.pop("disable_steam_input", None):
            data["steam_input_mode"] = "force_off"
        if data.pop("debug_logging", None):
            data["log_level"] = "debug"
        data["version"] = 1
    return data


def migrate_state(data: dict) -> dict:
    """Bring *data* from any older state schema to the current version."""
    # No migrations at v1 — infrastructure for future changes
    return data
