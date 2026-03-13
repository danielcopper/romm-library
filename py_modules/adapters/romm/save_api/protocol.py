"""Protocol definition for the RomM Save API adapter.

Services depend on this protocol, not on concrete implementations.
Concrete adapters implement this for different RomM API capabilities.
New adapters are only created when the API surface changes substantially
(new endpoints, removed workarounds, breaking changes) — not per release.
"""

from __future__ import annotations

from typing import Protocol


class SaveApiProtocol(Protocol):
    """Interface for save-related RomM API operations.

    Current adapters (VersionRouter selects based on detected server version):
      SaveApiV46 — RomM >= 4.6.1, < 4.7.0 (workarounds for missing endpoints)
      SaveApiV47 — RomM >= 4.7.0 (native endpoints, planned)

    No save sync support below 4.6.1.
    """

    async def list_saves(self, rom_id: int) -> list[dict]:
        """List all saves for a ROM.

        v46: GET /api/saves?rom_id={rom_id} — returns list directly.
        v47: Same endpoint, but response may include content_hash per save.
        """
        ...

    async def upload_save(
        self,
        rom_id: int,
        file_path: str,
        emulator: str,
        save_id: int | None = None,
    ) -> dict:
        """Upload (or update) a save file.

        v46: POST /api/saves (multipart, upserts by filename).
             PUT /api/saves/{save_id} when updating existing.
             Params: rom_id, emulator via query string.
        v47: Same, but may support content_hash in response.
        """
        ...

    async def download_save(self, save_id: int, dest_path: str) -> None:
        """Download a save file to a local path.

        v46: GET /api/saves/{save_id} for metadata, then download via
             download_path (URL-encoded). No /content endpoint.
        v47: GET /api/saves/{save_id}/content directly.
        """
        ...

    async def get_save_metadata(self, save_id: int) -> dict:
        """Fetch metadata for a single save.

        v46: GET /api/saves/{save_id}. No content_hash field —
             must download and hash to compare.
        v47: Same endpoint, but response includes content_hash.
        """
        ...

    async def get_rom_detail(self, rom_id: int) -> dict:
        """Fetch full ROM detail including user notes.

        Used to read playtime data from all_user_notes.
        v46: GET /api/roms/{rom_id}. Notes in all_user_notes field.
             GET /api/roms/{id}/notes returns 500 — must use this instead.
        v47: Same, or dedicated notes endpoint if fixed.
        """
        ...

    async def create_note(self, rom_id: int, data: dict) -> dict:
        """Create a note on a ROM (used for playtime tracking).

        v46: POST /api/roms/{rom_id}/notes with JSON body.
        v47: Same endpoint.
        """
        ...

    async def update_note(self, rom_id: int, note_id: int, data: dict) -> dict:
        """Update an existing note on a ROM.

        v46: PUT /api/roms/{rom_id}/notes/{note_id} with JSON body.
        v47: Same endpoint.
        """
        ...
