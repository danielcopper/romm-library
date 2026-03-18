"""Protocol interfaces for service dependencies.

Services depend on these protocols, not concrete adapter implementations.
This keeps the dependency direction clean: adapters implement protocols,
services consume them.
"""

from __future__ import annotations

from typing import Any, Protocol


class SteamConfigAdapter(Protocol):
    """Protocol for Steam configuration operations."""

    def grid_dir(self) -> str | None: ...
    def read_shortcuts(self) -> dict: ...
    def write_shortcuts(self, data: dict) -> None: ...
    def set_steam_input_config(self, app_ids: list, mode: str = "default") -> None: ...

    @staticmethod
    def generate_app_id(exe: str, appname: str) -> int: ...

    @staticmethod
    def generate_artwork_id(exe: str, appname: str) -> int: ...


class RommApiProtocol(Protocol):
    """Domain-oriented interface for all RomM server operations.

    Replaces raw HTTP path construction in services with semantic methods.
    Concrete implementations (RommApiBase for v4.6, RommApiV47 for v4.7+)
    handle URL building, version-specific quirks, and response parsing.

    ApiRouter selects the active implementation based on detected server version.
    """

    def set_version(self, version: str) -> None:
        """Set the detected RomM server version.

        Called after heartbeat to select the correct API implementation.
        """
        ...

    def heartbeat(self) -> dict:
        """Check server connectivity and retrieve version info.

        Returns the raw heartbeat response dict from /api/heartbeat.
        """
        ...

    def list_platforms(self) -> list[dict]:
        """Fetch all platforms configured on the RomM server.

        Returns a list of platform dicts from /api/platforms.
        """
        ...

    def get_current_user(self) -> dict:
        """Fetch the currently authenticated user profile.

        Returns user dict from /api/users/me.
        """
        ...

    def get_rom(self, rom_id: int) -> dict:
        """Fetch a single ROM by ID.

        Returns the ROM dict from /api/roms/{rom_id}.
        """
        ...

    def list_roms(self, platform_id: int, limit: int = 50, offset: int = 0) -> dict:
        """List ROMs for a platform with pagination.

        Returns paginated response {"items": [...], "total": N}
        from /api/roms filtered by platform_ids.
        """
        ...

    def list_roms_updated_after(
        self,
        platform_id: int,
        updated_after: str,
        limit: int = 1,
        offset: int = 0,
    ) -> dict:
        """List ROMs updated after a given timestamp.

        Used for incremental sync to detect changes since last sync.
        Returns paginated response filtered by updated_after parameter.
        """
        ...

    def download_rom_content(
        self,
        rom_id: int,
        filename: str,
        dest: str,
        progress_callback: Any = None,
    ) -> None:
        """Download a ROM file to a local destination.

        Streams /api/roms/{rom_id}/content/{filename} to dest.
        Filename is URL-encoded. Optional progress_callback for tracking.
        """
        ...

    def download_cover(self, cover_url: str, dest: str) -> None:
        """Download a ROM cover image to a local path.

        cover_url is the relative path from the RomM server.
        Spaces in the URL are encoded before downloading.
        """
        ...

    def list_firmware(self) -> list[dict]:
        """Fetch all available firmware/BIOS files from the server.

        Returns a list of firmware dicts from /api/firmware.
        """
        ...

    def get_firmware(self, firmware_id: int) -> dict:
        """Fetch metadata for a single firmware file.

        Returns firmware dict from /api/firmware/{firmware_id}.
        """
        ...

    def download_firmware(self, firmware_id: int, filename: str, dest: str) -> None:
        """Download a firmware/BIOS file to a local path.

        Streams /api/firmware/{firmware_id}/content/{filename} to dest.
        """
        ...

    def list_saves(self, rom_id: int) -> list[dict]:
        """List all saves for a ROM.

        Returns a list of save dicts from /api/saves?rom_id={rom_id}.
        """
        ...

    def upload_save(
        self,
        rom_id: int,
        file_path: str,
        emulator: str,
        save_id: int | None = None,
    ) -> dict:
        """Upload or update a save file.

        Creates via POST /api/saves or updates via PUT /api/saves/{save_id}.
        Upserts by filename. Returns the save dict.
        """
        ...

    def download_save(self, save_id: int, dest_path: str) -> None:
        """Download a save file to a local path.

        v4.6: Fetches metadata then downloads via download_path.
        v4.7+: Downloads directly via /api/saves/{save_id}/content.
        """
        ...

    def get_save_metadata(self, save_id: int) -> dict:
        """Fetch metadata for a single save.

        Returns save dict from /api/saves/{save_id}.
        """
        ...

    def get_rom_with_notes(self, rom_id: int) -> dict:
        """Fetch full ROM detail including user notes.

        Used for playtime tracking. Notes are in the all_user_notes field.
        v4.6: /api/roms/{id}/notes returns 500, so uses ROM detail endpoint.
        """
        ...

    def create_note(self, rom_id: int, data: dict) -> dict:
        """Create a note on a ROM.

        Used for playtime tracking. POST /api/roms/{rom_id}/notes.
        """
        ...

    def update_note(self, rom_id: int, note_id: int, data: dict) -> dict:
        """Update an existing note on a ROM.

        PUT /api/roms/{rom_id}/notes/{note_id}.
        """
        ...
