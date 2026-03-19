"""Version-aware router that delegates RommApiProtocol calls to the active implementation.

Defaults to RommApiBase (4.6, safe fallback). Call ``set_version()`` after
``heartbeat()`` detects the server version to switch to the appropriate
implementation.

``__getattr__`` acts as a safety net: any attribute not found on the router
itself raises ``RommUnsupportedError`` instead of a generic ``AttributeError``.
"""

from __future__ import annotations

from adapters.romm.api_base import RommApiBase
from adapters.romm.api_v47 import RommApiV47
from adapters.romm.http import RommHttpAdapter
from lib.errors import RommUnsupportedError


def _parse_version(version: str) -> tuple[int, ...] | None:
    """Parse a dotted version string into a tuple of ints, or None on failure."""
    try:
        return tuple(int(p) for p in version.split("."))
    except (ValueError, AttributeError):
        return None


_V47_THRESHOLD = (4, 7, 0)


class ApiRouter:
    """Selects the correct RommApi implementation based on detected RomM version.

    All 18 ``RommApiProtocol`` methods are explicitly delegated to ``self._active``.
    ``__getattr__`` catches anything else and raises ``RommUnsupportedError``.
    """

    def __init__(self, client: RommHttpAdapter) -> None:
        self._base = RommApiBase(client)
        self._v47 = RommApiV47(client)
        self._active = self._base

    def set_version(self, version: str) -> None:
        """Switch the active implementation based on the server version string.

        ``>= 4.7.0`` or ``"development"`` → V47, otherwise Base.
        """
        if version == "development":
            self._active = self._v47
            return
        parsed = _parse_version(version)
        if parsed is not None and parsed >= _V47_THRESHOLD:
            self._active = self._v47
        else:
            self._active = self._base

    # -- Explicit delegation of all 20 RommApiProtocol methods --

    def heartbeat(self) -> dict:
        return self._active.heartbeat()

    def list_platforms(self) -> list[dict]:
        return self._active.list_platforms()

    def list_collections(self) -> list[dict]:
        return self._active.list_collections()

    def list_virtual_collections(self, collection_type: str) -> list[dict]:
        return self._active.list_virtual_collections(collection_type)

    def get_current_user(self) -> dict:
        return self._active.get_current_user()

    def get_rom(self, rom_id: int) -> dict:
        return self._active.get_rom(rom_id)

    def list_roms(self, platform_id: int, limit: int = 50, offset: int = 0) -> dict:
        return self._active.list_roms(platform_id, limit, offset)

    def list_roms_updated_after(
        self,
        platform_id: int,
        updated_after: str,
        limit: int = 1,
        offset: int = 0,
    ) -> dict:
        return self._active.list_roms_updated_after(platform_id, updated_after, limit, offset)

    def download_rom_content(
        self,
        rom_id: int,
        filename: str,
        dest: str,
        progress_callback=None,
    ) -> None:
        self._active.download_rom_content(rom_id, filename, dest, progress_callback)

    def download_cover(self, cover_url: str, dest: str) -> None:
        self._active.download_cover(cover_url, dest)

    def list_firmware(self) -> list[dict]:
        return self._active.list_firmware()

    def get_firmware(self, firmware_id: int) -> dict:
        return self._active.get_firmware(firmware_id)

    def download_firmware(self, firmware_id: int, filename: str, dest: str) -> None:
        self._active.download_firmware(firmware_id, filename, dest)

    def list_saves(self, rom_id: int) -> list[dict]:
        return self._active.list_saves(rom_id)

    def upload_save(
        self,
        rom_id: int,
        file_path: str,
        emulator: str,
        save_id: int | None = None,
    ) -> dict:
        return self._active.upload_save(rom_id, file_path, emulator, save_id)

    def download_save(self, save_id: int, dest_path: str) -> None:
        self._active.download_save(save_id, dest_path)

    def get_save_metadata(self, save_id: int) -> dict:
        return self._active.get_save_metadata(save_id)

    def get_rom_with_notes(self, rom_id: int) -> dict:
        return self._active.get_rom_with_notes(rom_id)

    def create_note(self, rom_id: int, data: dict) -> dict:
        return self._active.create_note(rom_id, data)

    def update_note(self, rom_id: int, note_id: int, data: dict) -> dict:
        return self._active.update_note(rom_id, note_id, data)

    # -- Safety net --

    def __getattr__(self, name: str):
        """Raise RommUnsupportedError for any attribute not found on the router."""
        raise RommUnsupportedError(
            feature=name,
            min_version="unknown",
        )
