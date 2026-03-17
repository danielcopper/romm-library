"""RommApiProtocol implementation for RomM >= 4.7.0.

What's improved vs 4.6:
- Native GET /api/saves/{id}/content endpoint for downloads (no metadata
  round-trip needed).

FROZEN ADAPTER WARNING
──────────────────────
This file represents the RomM 4.7.0 API surface as it exists today.
Do NOT add features from future RomM versions (4.7.1, 4.8, etc.) here.
Create a new subclass instead (e.g. RommApiV471, RommApiV48) — users on
RomM 4.7.0 must remain supported with this exact behavior.
"""

from __future__ import annotations

from adapters.romm.api_base import RommApiBase


class RommApiV47(RommApiBase):
    """Concrete ``RommApiProtocol`` for RomM >= 4.7.0.

    Inherits everything from the base (4.6) except ``download_save``,
    which uses the native ``/content`` endpoint instead of the
    metadata + download_path workaround.
    """

    def download_save(self, save_id: int, dest_path: str) -> None:
        """Download via GET /api/saves/{id}/content (native 4.7.0 endpoint)."""
        self._client.download(f"/api/saves/{save_id}/content", dest_path)
