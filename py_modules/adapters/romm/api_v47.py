"""RommApiProtocol implementation for RomM >= 4.7.0.

Extends RommApiV46 with features available from 4.7.0 onwards:
- Native GET /api/saves/{id}/content (no metadata round-trip)
- Collections API (list, virtual, ROM-by-collection queries)

This represents the CURRENT active RomM API surface and may be extended
for features confirmed on 4.7.0. For features from future RomM versions
(4.8, etc.), create a new subclass (e.g. RommApiV48(RommApiV47)).
"""

from __future__ import annotations

import urllib.parse

from adapters.romm.api_v46 import RommApiV46


class RommApiV47(RommApiV46):
    """Concrete RommApiProtocol for RomM >= 4.7.0."""

    def download_save(self, save_id: int, dest_path: str) -> None:
        """Download via GET /api/saves/{id}/content (native 4.7.0 endpoint)."""
        self._client.download(f"/api/saves/{save_id}/content", dest_path)

    def list_collections(self) -> list[dict]:
        result = self._client.request("/api/collections")
        return result if isinstance(result, list) else []

    def list_virtual_collections(self, collection_type: str) -> list[dict]:
        result = self._client.request(f"/api/collections/virtual?type={collection_type}")
        return result if isinstance(result, list) else []

    def list_roms_by_collection(self, collection_id: int, limit: int = 50, offset: int = 0) -> dict:
        return self._client.request(f"/api/roms?collection_id={collection_id}&limit={limit}&offset={offset}")

    def list_roms_by_virtual_collection(self, virtual_id: str, limit: int = 50, offset: int = 0) -> dict:
        encoded_id = urllib.parse.quote(str(virtual_id), safe="")
        return self._client.request(f"/api/roms?virtual_collection_id={encoded_id}&limit={limit}&offset={offset}")

    def list_saves(
        self,
        rom_id: int,
        *,
        device_id: str | None = None,
        slot: str | None = None,
    ) -> list[dict]:
        """List saves with optional device sync info and slot filtering."""
        query = f"/api/saves?rom_id={rom_id}"
        if device_id is not None:
            query += f"&device_id={device_id}"
        if slot is not None:
            query += f"&slot={slot}"
        result = self._client.request(query)
        return result if isinstance(result, list) else []

    def upload_save(
        self,
        rom_id: int,
        file_path: str,
        emulator: str,
        save_id: int | None = None,
        *,
        device_id: str | None = None,
        slot: str | None = None,
        overwrite: bool = False,
    ) -> dict:
        """Upload a save with optional device tracking and slot assignment.

        Raises RommConflictError on 409 (another device uploaded since last sync).
        """
        params = f"rom_id={rom_id}&emulator={urllib.parse.quote(emulator)}"
        if device_id is not None:
            params += f"&device_id={device_id}"
        if slot is not None:
            params += f"&slot={slot}"
        if overwrite:
            params += "&overwrite=true"
        if save_id is not None:
            return self._client.upload_multipart(f"/api/saves/{save_id}?{params}", file_path, method="PUT")
        return self._client.upload_multipart(f"/api/saves?{params}", file_path, method="POST")

    def download_save_content(
        self,
        save_id: int,
        dest_path: str,
        *,
        device_id: str | None = None,
        optimistic: bool = True,
    ) -> None:
        """Download save content with optional device sync tracking.

        When device_id is provided, the server records the download.
        optimistic=True (default) auto-marks device as synced.
        optimistic=False requires a manual confirm_download() call after.
        """
        path = f"/api/saves/{save_id}/content"
        if device_id is not None:
            opt = "true" if optimistic else "false"
            path += f"?device_id={device_id}&optimistic={opt}"
        self._client.download(path, dest_path)

    def confirm_download(self, save_id: int, device_id: str) -> dict:
        """Confirm a save download for manual sync (when optimistic=false)."""
        return self._client.post_json(
            f"/api/saves/{save_id}/downloaded",
            {"device_id": device_id},
        )

    def get_save_summary(self, rom_id: int, device_id: str | None = None) -> dict:
        """Fetch grouped save summary for a ROM with slot breakdown.

        Uses the dedicated /api/saves/summary endpoint which returns
        a structured response grouped by slot, unlike the flat list
        from list_saves.
        """
        query = f"/api/saves/summary?rom_id={rom_id}"
        if device_id is not None:
            query += f"&device_id={device_id}"
        return self._client.request(query)

    def delete_server_saves(self, save_ids: list[int]) -> dict:
        """Delete saves from the RomM server by ID."""
        return self._client.post_json("/api/saves/delete", {"saves": save_ids})

    def register_device(self, name: str, platform: str, client: str, version: str) -> dict:
        """Register this client as a device via POST /api/devices."""
        return self._client.post_json(
            "/api/devices",
            {
                "name": name,
                "platform": platform,
                "client": client,
                "version": version,
            },
        )
