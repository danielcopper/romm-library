"""Protocol interfaces for service dependencies.

Services depend on these protocols, not concrete adapter implementations.
This keeps the dependency direction clean: adapters implement protocols,
services consume them.
"""

from __future__ import annotations

import ssl
from typing import Any, Protocol


class HttpAdapter(Protocol):
    """Protocol for HTTP operations against the RomM API."""

    def request(self, path: str) -> Any: ...
    def download(self, path: str, dest: str, progress_callback: Any = None) -> None: ...
    def download_file(
        self, rom_id: int, file_name: str, dest: str, progress_callback: Any = None, resume_from: int = 0
    ) -> None: ...
    def json_request(self, path: str, data: Any, method: str = "POST") -> Any: ...
    def post_json(self, path: str, data: Any) -> Any: ...
    def put_json(self, path: str, data: Any) -> Any: ...
    def upload_multipart(self, path: str, file_path: str, method: str = "POST") -> Any: ...
    def with_retry(self, fn: Any, *args: Any, max_attempts: int = 3, base_delay: int = 1, **kwargs: Any) -> Any: ...

    @staticmethod
    def is_retryable(exc: Exception) -> bool: ...

    def resolve_system(self, platform_slug: str, platform_fs_slug: str | None = None) -> str: ...
    def load_platform_map(self) -> dict: ...
    def ssl_context(self) -> ssl.SSLContext: ...
    def auth_header(self) -> str: ...
    def translate_http_error(self, exc: Exception, url: str, method: str = "GET") -> Exception: ...


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


class SaveApiProtocol(Protocol):
    """Interface for save-related RomM API operations.

    Current adapters (VersionRouter selects based on detected server version):
      SaveApiV46 — RomM >= 4.6.1, < 4.7.0 (workarounds for missing endpoints)
      SaveApiV47 — RomM >= 4.7.0 (native endpoints, planned)

    No save sync support below 4.6.1.
    """

    def list_saves(self, rom_id: int) -> list[dict]:
        """List all saves for a ROM.

        v46: GET /api/saves?rom_id={rom_id} — returns list directly.
        v47: Same endpoint, but response may include content_hash per save.
        """
        ...

    def upload_save(
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

    def download_save(self, save_id: int, dest_path: str) -> None:
        """Download a save file to a local path.

        v46: GET /api/saves/{save_id} for metadata, then download via
             download_path (URL-encoded). No /content endpoint.
        v47: GET /api/saves/{save_id}/content directly.
        """
        ...

    def get_save_metadata(self, save_id: int) -> dict:
        """Fetch metadata for a single save.

        v46: GET /api/saves/{save_id}. No content_hash field —
             must download and hash to compare.
        v47: Same endpoint, but response includes content_hash.
        """
        ...

    def get_rom_detail(self, rom_id: int) -> dict:
        """Fetch full ROM detail including user notes.

        Used to read playtime data from all_user_notes.
        v46: GET /api/roms/{rom_id}. Notes in all_user_notes field.
             GET /api/roms/{id}/notes returns 500 — must use this instead.
        v47: Same, or dedicated notes endpoint if fixed.
        """
        ...

    def create_note(self, rom_id: int, data: dict) -> dict:
        """Create a note on a ROM (used for playtime tracking).

        v46: POST /api/roms/{rom_id}/notes with JSON body.
        v47: Same endpoint.
        """
        ...

    def update_note(self, rom_id: int, note_id: int, data: dict) -> dict:
        """Update an existing note on a ROM.

        v46: PUT /api/roms/{rom_id}/notes/{note_id} with JSON body.
        v47: Same endpoint.
        """
        ...
