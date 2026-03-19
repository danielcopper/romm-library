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
