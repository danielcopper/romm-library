"""Proxy that delegates to the correct SaveApi adapter based on detected RomM server version.

Defaults to v46 (safe fallback). Call ``set_version()`` after
``test_connection()`` detects the server version.
"""

from __future__ import annotations

from adapters.romm.http import RommHttpAdapter
from adapters.romm.save_api.v46 import SaveApiV46
from adapters.romm.save_api.v47 import SaveApiV47


def _parse_version(version: str) -> tuple[int, ...] | None:
    """Parse a dotted version string into a tuple of ints, or None on failure."""
    try:
        return tuple(int(p) for p in version.split("."))
    except (ValueError, AttributeError):
        return None


_V47_THRESHOLD = (4, 7, 0)


class VersionRouter:
    """Selects the correct SaveApi adapter based on detected RomM version."""

    def __init__(self, client: RommHttpAdapter) -> None:
        self._v46 = SaveApiV46(client)
        self._v47 = SaveApiV47(client)
        self._active = self._v46

    def set_version(self, version: str) -> None:
        """Switch adapter based on version string.

        ``>= 4.7.0`` or ``"development"`` → v47, otherwise v46.
        """
        if version == "development":
            self._active = self._v47
            return
        parsed = _parse_version(version)
        if parsed is not None and parsed >= _V47_THRESHOLD:
            self._active = self._v47
        else:
            self._active = self._v46

    # -- Delegate all SaveApiProtocol methods to self._active --

    async def list_saves(self, rom_id: int) -> list[dict]:
        return await self._active.list_saves(rom_id)

    async def upload_save(
        self,
        rom_id: int,
        file_path: str,
        emulator: str,
        save_id: int | None = None,
    ) -> dict:
        return await self._active.upload_save(rom_id, file_path, emulator, save_id)

    async def download_save(self, save_id: int, dest_path: str) -> None:
        return await self._active.download_save(save_id, dest_path)

    async def get_save_metadata(self, save_id: int) -> dict:
        return await self._active.get_save_metadata(save_id)

    async def get_rom_detail(self, rom_id: int) -> dict:
        return await self._active.get_rom_detail(rom_id)

    async def create_note(self, rom_id: int, data: dict) -> dict:
        return await self._active.create_note(rom_id, data)

    async def update_note(self, rom_id: int, note_id: int, data: dict) -> dict:
        return await self._active.update_note(rom_id, note_id, data)
