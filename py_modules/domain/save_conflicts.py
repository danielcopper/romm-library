"""Pure save-file conflict detection and resolution logic.

No I/O, no service/adapter/lib imports. All functions are stateless and
operate only on the values passed to them.
"""

from __future__ import annotations

from datetime import datetime, timezone


def check_local_changes(local_hash: str | None, last_sync_hash: str) -> bool:
    """Return True if the local file has changed since the last sync.

    Parameters
    ----------
    local_hash:
        MD5 hex digest of the current local file (may be empty/None if missing).
    last_sync_hash:
        MD5 hex digest recorded at the last successful sync.
    """
    return local_hash != last_sync_hash


def check_server_changes_fast(
    file_state: dict,
    server_save: dict,
    last_sync_hash: str,
) -> bool | None:
    """Fast-path server-change detection using stored timestamp and size.

    Returns
    -------
    False
        Server is definitely unchanged (timestamp+size match AND last_sync_hash
        is present so we have a valid baseline to compare against).
    True
        Server has definitely changed (size differs on a timestamp-matched save).
    None
        Indeterminate — timestamp changed (or no stored timestamp); the caller
        must fall back to a slow-path hash comparison.
    """
    stored_updated_at = file_state.get("last_sync_server_updated_at")
    stored_size = file_state.get("last_sync_server_size")
    server_updated_at = server_save.get("updated_at", "")
    server_size = server_save.get("file_size_bytes")

    # Fast path: timestamp unchanged
    if stored_updated_at and server_updated_at == stored_updated_at:
        if stored_size is not None and server_size is not None and server_size != stored_size:
            return True  # size changed despite same timestamp
        return False  # unchanged

    # Timestamp changed or no stored timestamp — indeterminate without hash
    return None


def determine_action(local_changed: bool, server_changed: bool) -> str:
    """Decide the sync action from local and server change flags.

    Returns
    -------
    str
        One of ``"skip"``, ``"upload"``, ``"download"``, or ``"conflict"``.
    """
    if not local_changed and not server_changed:
        return "skip"
    if not local_changed:
        return "download"
    if not server_changed:
        return "upload"
    return "conflict"


def detect_conflict_lightweight(
    local_mtime: float,
    local_size: int,
    server_save: dict | None,
    file_state: dict,
) -> str:
    """Timestamp-only conflict detection — no file hashing, no server downloads.

    Parameters
    ----------
    local_mtime:
        Modification time of the local save file (seconds since epoch).
    local_size:
        Size of the local save file in bytes.
    server_save:
        Server save metadata dict, or ``None`` if no server save exists.
    file_state:
        Per-file sync state from ``save_sync_state["saves"][rom_id]["files"][filename]``.

    Returns
    -------
    str
        One of ``"skip"``, ``"upload"``, ``"download"``, or ``"conflict"``.
    """
    last_sync_hash = file_state.get("last_sync_hash")

    # Never synced — can't determine state without hashing
    if not last_sync_hash:
        return "conflict" if server_save else "upload"

    # Local change: compare mtime against stored sync mtime
    stored_local_mtime = file_state.get("last_sync_local_mtime")
    if stored_local_mtime is not None:
        local_changed = abs(local_mtime - stored_local_mtime) > 1.0
    else:
        # No stored mtime — fall back to size comparison
        stored_local_size = file_state.get("last_sync_local_size")
        local_changed = stored_local_size is not None and local_size != stored_local_size

    # Server change detection
    server_changed = False
    if server_save:
        stored_updated_at = file_state.get("last_sync_server_updated_at")
        stored_size = file_state.get("last_sync_server_size")
        server_updated_at = server_save.get("updated_at", "")
        server_size = server_save.get("file_size_bytes")

        if (stored_updated_at and server_updated_at != stored_updated_at) or (
            stored_size is not None and server_size is not None and server_size != stored_size
        ):
            server_changed = True

    return determine_action(local_changed, server_changed)


def resolve_conflict_by_mode(
    mode: str,
    local_mtime: float,
    server_save: dict,
    tolerance: float = 60.0,
) -> str:
    """Apply a conflict resolution mode.

    Parameters
    ----------
    mode:
        One of ``"ask_me"``, ``"always_upload"``, ``"always_download"``,
        or ``"newest_wins"``.
    local_mtime:
        Modification time of the local save file (seconds since epoch).
    server_save:
        Server save metadata dict (needs ``"updated_at"`` ISO-8601 string).
    tolerance:
        Clock-skew tolerance in seconds used by ``"newest_wins"`` mode.
        Defaults to ``60``.

    Returns
    -------
    str
        One of ``"upload"``, ``"download"``, or ``"ask"``.
    """
    if mode == "always_upload":
        return "upload"
    if mode == "always_download":
        return "download"
    if mode == "ask_me":
        return "ask"

    # newest_wins (default fallback for unrecognised modes too)
    server_updated = server_save.get("updated_at", "")
    try:
        server_dt = datetime.fromisoformat(server_updated.replace("Z", "+00:00"))
        local_dt = datetime.fromtimestamp(local_mtime, tz=timezone.utc)
        diff = abs((local_dt - server_dt).total_seconds())
        if diff <= tolerance:
            return "ask"
        return "upload" if local_dt > server_dt else "download"
    except (ValueError, TypeError):
        return "ask"


def build_conflict_dict(
    rom_id: int,
    filename: str,
    local_info: dict | None,
    local_hash: str | None,
    server_save: dict,
) -> dict:
    """Build a conflict descriptor for the frontend.

    Parameters
    ----------
    rom_id:
        Integer ROM identifier.
    filename:
        Save filename (e.g. ``"pokemon.srm"``).
    local_info:
        Pre-computed local file metadata with keys ``"path"``, ``"mtime"``
        (float seconds since epoch, or ``None``), and ``"size"`` (int, or
        ``None``).  Pass ``None`` if no local file exists.
    local_hash:
        MD5 hex digest of the local file, or ``None``.
    server_save:
        Server save metadata dict.

    Returns
    -------
    dict
        Conflict descriptor ready for the frontend.
    """
    local_mtime_val: float | None = local_info.get("mtime") if local_info else None
    return {
        "rom_id": rom_id,
        "filename": filename,
        "local_path": local_info["path"] if local_info else None,
        "local_hash": local_hash,
        "local_mtime": (
            datetime.fromtimestamp(local_mtime_val, tz=timezone.utc).isoformat()
            if local_mtime_val is not None
            else None
        ),
        "local_size": local_info.get("size") if local_info else None,
        "server_save_id": server_save.get("id"),
        "server_updated_at": server_save.get("updated_at", ""),
        "server_size": server_save.get("file_size_bytes"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
