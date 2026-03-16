"""SaveApi adapter for RomM >= 4.7.0.

What's improved vs v46:
- Native GET /api/saves/{id}/content endpoint for downloads (no metadata
  round-trip needed).

What's postponed (and why):
- content_hash: field exists in schema but is null on real 4.7.0 servers.
  Still requires download-and-hash for change detection.
- device_id / device tracking: accepted by server but adds registration
  overhead with no functional benefit yet.

FROZEN ADAPTER WARNING
──────────────────────
This file represents the RomM 4.7.0 API surface as it exists today.
Do NOT add features from future RomM versions (4.7.1, 4.8, etc.) here.
Create a new adapter file instead (e.g. v471.py, v48.py) — users on
RomM 4.7.0 must remain supported with this exact behavior.
"""

from __future__ import annotations

from adapters.romm.save_api.v46 import SaveApiV46


class SaveApiV47(SaveApiV46):
    """Concrete ``SaveApiProtocol`` for RomM >= 4.7.0.

    Inherits everything from v46 except ``download_save``, which uses
    the native ``/content`` endpoint instead of the metadata+download_path
    workaround.
    """

    def download_save(self, save_id: int, dest_path: str) -> None:
        """Download via GET /api/saves/{id}/content (native 4.7.0 endpoint)."""
        self._client.download(f"/api/saves/{save_id}/content", dest_path)
