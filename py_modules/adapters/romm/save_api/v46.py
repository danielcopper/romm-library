"""SaveApi adapter for RomM >= 4.6.1, < 4.7.0.

Workarounds for missing/broken endpoints in 4.6.x:
- No GET /api/saves/{id}/content — fetch metadata, extract download_path
- No content_hash in save metadata — must download and hash
- GET /api/roms/{id}/notes returns 500 — read all_user_notes from ROM detail
- device_id param accepted but ignored
"""

from __future__ import annotations

import urllib.parse

from adapters.romm.http import RommHttpAdapter


class SaveApiV46:
    """Concrete ``SaveApiProtocol`` for RomM 4.6.x."""

    def __init__(self, client: RommHttpAdapter) -> None:
        self._client = client

    def list_saves(self, rom_id: int) -> list[dict]:
        """List saves for a ROM. Returns plain array."""
        result = self._client.request(f"/api/saves?rom_id={rom_id}")
        if isinstance(result, list):
            return result
        return []

    def upload_save(
        self,
        rom_id: int,
        file_path: str,
        emulator: str,
        save_id: int | None = None,
    ) -> dict:
        """Upload or update a save file.

        POST upserts by filename. PUT for explicit update when save_id given.
        rom_id and emulator passed as query params.
        """
        params = f"rom_id={rom_id}&emulator={urllib.parse.quote(emulator)}"

        if save_id:
            return self._client.upload_multipart(f"/api/saves/{save_id}?{params}", file_path, method="PUT")
        return self._client.upload_multipart(f"/api/saves?{params}", file_path, method="POST")

    def download_save(self, save_id: int, dest_path: str) -> None:
        """Download a save file.

        GET /api/saves/{id}/content does NOT exist on 4.6.1.
        Fetches metadata first, extracts download_path, URL-encodes it,
        then downloads binary.
        """
        metadata = self._client.request(f"/api/saves/{save_id}")
        download_path = metadata.get("download_path", "")
        if not download_path:
            raise ValueError(f"Save {save_id} has no download_path")
        encoded_path = urllib.parse.quote(download_path, safe="/")
        self._client.download(encoded_path, dest_path)

    def get_save_metadata(self, save_id: int) -> dict:
        """Fetch metadata for a single save. No content_hash on 4.6.x."""
        return self._client.request(f"/api/saves/{save_id}")

    def get_rom_detail(self, rom_id: int) -> dict:
        """Fetch full ROM detail including all_user_notes.

        Used because GET /api/roms/{id}/notes returns 500 on 4.6.1.
        """
        return self._client.request(f"/api/roms/{rom_id}")

    def create_note(self, rom_id: int, data: dict) -> dict:
        """Create a note on a ROM (POST /api/roms/{rom_id}/notes)."""
        return self._client.post_json(f"/api/roms/{rom_id}/notes", data)

    def update_note(self, rom_id: int, note_id: int, data: dict) -> dict:
        """Update an existing note (PUT /api/roms/{rom_id}/notes/{note_id})."""
        return self._client.put_json(f"/api/roms/{rom_id}/notes/{note_id}", data)
