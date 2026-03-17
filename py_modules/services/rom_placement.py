"""rom_placement.py — Platform-specific post-download file placement.

After a multi-file ROM is downloaded, some platforms require files to be
placed in specific locations. This module provides a registry of placement
functions keyed by platform slug.
"""

from __future__ import annotations

import os
import re
import shutil
from typing import TYPE_CHECKING

from lib import retrodeck_config

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable

_WIIU_FOLDER_RE = re.compile(r"\[(Game|Update|DLC)\]\s*\[([0-9a-fA-F]{1,32})\]")

# Cemu mlc01 title base paths by WiiU content type
_WIIU_TYPE_SUBPATH = {
    "Update": os.path.join("cemu", "mlc01", "usr", "title", "0005000e"),
    "DLC": os.path.join("cemu", "mlc01", "usr", "title", "0005000c"),
}


def _default_placement(_rom_dir: str, _files: list, _logger: logging.Logger) -> None:
    """No-op placement — used for platforms that need no special file handling."""


def place_wiiu(rom_dir: str, _files: list, logger: logging.Logger) -> None:
    """Move WiiU Update/DLC folders into their Cemu mlc01 locations.

    RomM names WiiU folders like:
        The Legend of Zelda Breath of the Wild [Game] [00050000101c9400]

    [Game] folders stay in rom_dir untouched. [Update] and [DLC] folders are
    relocated to {bios_path}/cemu/mlc01/usr/title/{type_id}/{title_id}/.
    """
    bios_path = retrodeck_config.get_bios_path()
    if not bios_path:
        logger.warning("place_wiiu: bios path not available, skipping placement")
        return

    try:
        entries = os.listdir(rom_dir)
    except OSError as exc:
        logger.warning("place_wiiu: cannot list rom_dir %s: %s", rom_dir, exc)
        return

    for entry in entries:
        match = _WIIU_FOLDER_RE.search(entry)
        if not match:
            continue

        content_type = match.group(1)  # Game, Update, or DLC
        title_id = match.group(2).lower()

        if content_type == "Game":
            continue  # stays in rom_dir as-is

        type_subpath = _WIIU_TYPE_SUBPATH.get(content_type)
        if type_subpath is None:
            continue

        src = os.path.join(rom_dir, entry)
        if not os.path.isdir(src):
            continue

        dest = os.path.join(bios_path, type_subpath, title_id)

        try:
            os.makedirs(dest, exist_ok=True)
            for item in os.listdir(src):
                shutil.move(os.path.join(src, item), os.path.join(dest, item))
            os.rmdir(src)
            logger.info("place_wiiu: moved %s -> %s", src, dest)
        except OSError as exc:
            logger.warning("place_wiiu: failed to move %s -> %s: %s", src, dest, exc)


PLATFORM_PLACEMENT: dict[str, Callable] = {
    "wiiu": place_wiiu,
}


def get_placement(platform_slug: str) -> Callable:
    """Return the placement function for the given platform slug.

    Falls back to _default_placement (no-op) for unknown platforms.
    """
    return PLATFORM_PLACEMENT.get(platform_slug, _default_placement)
