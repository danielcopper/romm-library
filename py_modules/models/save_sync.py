"""Domain dataclasses for save sync.

NOTE: These dataclasses are not yet consumed by services — they exist as
the target domain model for a future refactor that replaces raw dicts
in SaveService and PlaytimeService with typed dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SaveFile:
    """A save file that exists locally and/or on the server."""

    filename: str
    rom_id: int
    local_path: str | None = None
    local_hash: str | None = None
    local_mtime: float | None = None
    local_size: int | None = None
    server_save_id: int | None = None
    server_hash: str | None = None
    server_mtime: str | None = None
    server_size: int | None = None


@dataclass
class SaveConflict:
    """A detected conflict between local and server save."""

    rom_id: int
    filename: str
    server_save_id: int
    local_path: str
    local_hash: str
    local_mtime: float
    local_size: int
    server_hash: str
    server_mtime: str
    server_size: int


@dataclass
class PlaytimeEntry:
    """Tracked playtime for a ROM."""

    rom_id: int
    total_seconds: int = 0
    last_session_start_at: str | None = None
    last_session_start_unix: int | None = None
    note_id: int | None = None
