"""Emulator tag construction for RomM save uploads.

The emulator tag determines the server-side folder path for saves:
saves/{system}/{rom_id}/{emulator}/

Format: retroarch-{core} where core is the libretro core name
without the _libretro suffix, lowercased.

No I/O, no service/adapter/lib imports. Pure functions only.
"""

from __future__ import annotations

_LIBRETRO_SUFFIX = "_libretro"
_FALLBACK = "retroarch"


def build_emulator_tag(core_so: str | None) -> str:
    """Build a RomM emulator tag from a RetroArch core .so name.

    Parameters
    ----------
    core_so:
        The libretro core name as found in ES-DE config, e.g. "mgba_libretro",
        "snes9x_libretro", "swanstation_libretro".
        May be None if core resolution failed.

    Returns
    -------
    str
        Emulator tag string, e.g. "retroarch-mgba", "retroarch-snes9x".
        Returns "retroarch" as fallback when core_so is None or empty.

    Rules:
    - Strip "_libretro" suffix
    - Lowercase
    - Prepend "retroarch-"
    - Fallback to "retroarch" if core_so is None/empty
    """
    if not core_so:
        return _FALLBACK
    core = core_so.lower()
    if core.endswith(_LIBRETRO_SUFFIX):
        core = core[: -len(_LIBRETRO_SUFFIX)]
    return f"retroarch-{core}"


def detect_core_change(stored_core: str | None, active_core: str | None) -> bool:
    """Detect if the active RetroArch core has changed since last sync.

    Parameters
    ----------
    stored_core:
        The core_so name recorded at last sync, or None if never synced.
    active_core:
        The currently active core_so name, or None if unresolved.

    Returns
    -------
    bool
        True if the cores differ and both are non-None (actual change).
        False if either is None (can't determine) or they match.
    """
    if stored_core is None or active_core is None:
        return False
    return stored_core != active_core
