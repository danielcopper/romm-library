"""Version-aware router that delegates all RommApiProtocol calls to the active implementation.

Defaults to RommApiV46 (safe fallback). Call set_version() after heartbeat()
detects the server version to switch to the appropriate implementation.

All API method calls are forwarded via __getattr__ — no explicit delegation needed.
"""

from __future__ import annotations

from adapters.romm.api_v46 import RommApiV46
from adapters.romm.api_v47 import RommApiV47
from adapters.romm.http import RommHttpAdapter


def _parse_version(version: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(p) for p in version.split("."))
    except (ValueError, AttributeError):
        return None


_V47_THRESHOLD = (4, 7, 0)


class ApiRouter:
    """Selects the correct RommApi implementation based on detected RomM version.

    All method calls are delegated to self._active via __getattr__.
    If the active implementation doesn't have a method, Python's MRO will
    reach RommApiBase.__getattr__ which raises RommUnsupportedError.
    """

    def __init__(self, client: RommHttpAdapter) -> None:
        self._v46 = RommApiV46(client)
        self._v47 = RommApiV47(client)
        self._active: RommApiV46 = self._v46

    def set_version(self, version: str) -> None:
        """Switch the active implementation based on the server version string."""
        if version == "development":
            self._active = self._v47
            return
        parsed = _parse_version(version)
        if parsed is not None and parsed >= _V47_THRESHOLD:
            self._active = self._v47
        else:
            self._active = self._v46

    def supports_device_sync(self) -> bool:
        """Check if the active RomM version supports device sync features."""
        return isinstance(self._active, RommApiV47)

    def __getattr__(self, name: str):
        return getattr(self._active, name)
