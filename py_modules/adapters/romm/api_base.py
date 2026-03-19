"""Abstract base for all RomM API version adapters.

Contains only the shared constructor and a __getattr__ catch-all that raises
RommUnsupportedError for any method not implemented by a version subclass.
Do NOT add API methods here — implement them in the appropriate version adapter.
"""

from __future__ import annotations

from adapters.romm.http import RommHttpAdapter
from lib.errors import RommUnsupportedError


class RommApiBase:
    """Base class for versioned RomM API adapters.

    Subclasses (RommApiV46, RommApiV47, etc.) implement actual API methods.
    Any method not implemented by the active version adapter will fall through
    to __getattr__ and raise RommUnsupportedError.
    """

    def __init__(self, client: RommHttpAdapter) -> None:
        self._client = client

    def __getattr__(self, name: str):
        raise RommUnsupportedError(feature=name, min_version="unknown")
