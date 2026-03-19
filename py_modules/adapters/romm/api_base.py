"""RommApiProtocol implementation for RomM 4.6.x (baseline behavior).

This is the base implementation that all version-specific subclasses extend.
It delegates HTTP transport to RommHttpAdapter and handles URL construction,
encoding, and response normalization.

v4.6 quirks handled here:
- download_save: No /content endpoint — fetch metadata, extract download_path
- get_rom_with_notes: /api/roms/{id}/notes returns 500 — use ROM detail
- list_saves: response may not be a list — normalize to []
"""

from __future__ import annotations

import urllib.parse

from adapters.romm.http import RommHttpAdapter


class RommApiBase:
    """Concrete ``RommApiProtocol`` for RomM 4.6.x."""

    def __init__(self, client: RommHttpAdapter) -> None:
        self._client = client

    def set_version(self, version: str) -> None:
        """No-op on base — version routing handled by ApiRouter."""

    def heartbeat(self) -> dict:
        return self._client.request("/api/heartbeat")

    def list_platforms(self) -> list[dict]:
        return self._client.request("/api/platforms")

    def list_collections(self) -> list[dict]:
        result = self._client.request("/api/collections")
        return result if isinstance(result, list) else []

    def list_virtual_collections(self, collection_type: str) -> list[dict]:
        result = self._client.request(f"/api/collections/virtual?type={collection_type}")
        return result if isinstance(result, list) else []

    def get_current_user(self) -> dict:
        return self._client.request("/api/users/me")

    def get_rom(self, rom_id: int) -> dict:
        return self._client.request(f"/api/roms/{rom_id}")

    def list_roms(self, platform_id: int, limit: int = 50, offset: int = 0) -> dict:
        return self._client.request(f"/api/roms?platform_ids={platform_id}&limit={limit}&offset={offset}")

    def list_roms_updated_after(
        self,
        platform_id: int,
        updated_after: str,
        limit: int = 1,
        offset: int = 0,
    ) -> dict:
        quoted_after = urllib.parse.quote(updated_after)
        return self._client.request(
            f"/api/roms?platform_ids={platform_id}&limit={limit}&offset={offset}&updated_after={quoted_after}"
        )

    def download_rom_content(
        self,
        rom_id: int,
        filename: str,
        dest: str,
        progress_callback=None,
    ) -> None:
        quoted_filename = urllib.parse.quote(filename, safe="")
        self._client.download(
            f"/api/roms/{rom_id}/content/{quoted_filename}",
            dest,
            progress_callback,
        )

    def download_cover(self, cover_url: str, dest: str) -> None:
        self._client.download(cover_url, dest)

    def list_firmware(self) -> list[dict]:
        return self._client.request("/api/firmware")

    def get_firmware(self, firmware_id: int) -> dict:
        return self._client.request(f"/api/firmware/{firmware_id}")

    def download_firmware(self, firmware_id: int, filename: str, dest: str) -> None:
        quoted_filename = urllib.parse.quote(filename, safe="")
        self._client.download(
            f"/api/firmware/{firmware_id}/content/{quoted_filename}",
            dest,
        )

    def list_saves(self, rom_id: int) -> list[dict]:
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
        params = f"rom_id={rom_id}&emulator={urllib.parse.quote(emulator)}"
        if save_id is not None:
            return self._client.upload_multipart(f"/api/saves/{save_id}?{params}", file_path, method="PUT")
        return self._client.upload_multipart(f"/api/saves?{params}", file_path, method="POST")

    def download_save(self, save_id: int, dest_path: str) -> None:
        metadata = self._client.request(f"/api/saves/{save_id}")
        download_path = metadata.get("download_path", "")
        if not download_path:
            raise ValueError(f"Save {save_id} has no download_path")
        encoded_path = urllib.parse.quote(download_path, safe="/")
        self._client.download(encoded_path, dest_path)

    def get_save_metadata(self, save_id: int) -> dict:
        return self._client.request(f"/api/saves/{save_id}")

    def get_rom_with_notes(self, rom_id: int) -> dict:
        return self._client.request(f"/api/roms/{rom_id}")

    def create_note(self, rom_id: int, data: dict) -> dict:
        return self._client.post_json(f"/api/roms/{rom_id}/notes", data)

    def update_note(self, rom_id: int, note_id: int, data: dict) -> dict:
        return self._client.put_json(f"/api/roms/{rom_id}/notes/{note_id}", data)
