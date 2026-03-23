"""Per-platform save file extension configuration.

Provides the list of save file extensions to look for when syncing saves.
The default covers RetroArch's standard .srm and .rtc extensions.
Platform-specific overrides can expand or replace this list.

Extension expansion (adding .sav, .mcr, .mcd, etc.) is tracked in #186.

No I/O, no service/adapter/lib imports. Pure functions only.
"""

from __future__ import annotations

_DEFAULT_EXTENSIONS: tuple[str, ...] = (".srm", ".rtc")

# Platform-specific overrides. Keys are RomM platform slugs.
# Values completely replace the default list for that platform.
# Populated incrementally as gameplay tests confirm actual extensions.
_PLATFORM_OVERRIDES: dict[str, tuple[str, ...]] = {
    # Example (to be filled in #186):
    # "n64": (".srm", ".rtc", ".eep", ".sra", ".fla", ".mpk"),
}


def get_save_extensions(platform_slug: str | None = None) -> tuple[str, ...]:
    """Return the save file extensions to search for a given platform.

    Parameters
    ----------
    platform_slug:
        RomM platform slug (e.g. "gba", "n64", "psx").
        If None or not in overrides, returns the default extensions.

    Returns
    -------
    tuple[str, ...]
        Tuple of file extensions including the leading dot (e.g. (".srm", ".rtc")).
    """
    if platform_slug is not None and platform_slug in _PLATFORM_OVERRIDES:
        return _PLATFORM_OVERRIDES[platform_slug]
    return _DEFAULT_EXTENSIONS


def get_all_known_extensions() -> tuple[str, ...]:
    """Return all unique extensions across defaults and all platform overrides.

    Useful for broad file discovery or migration tooling.
    """
    seen: set[str] = set()
    result: list[str] = []
    for ext in _DEFAULT_EXTENSIONS:
        if ext not in seen:
            seen.add(ext)
            result.append(ext)
    for exts in _PLATFORM_OVERRIDES.values():
        for ext in exts:
            if ext not in seen:
                seen.add(ext)
                result.append(ext)
    return tuple(result)
