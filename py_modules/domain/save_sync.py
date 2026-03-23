"""Unified sync-action logic for save sync v2.

Extends the existing conflict detection (save_conflicts.py) with
RomM v4.7 device sync awareness (is_current flag from device_syncs).

No I/O, no service/adapter/lib imports. Pure functions only.
"""

from __future__ import annotations

from domain.save_conflicts import check_server_changes_fast, determine_action


def check_server_changed_v47(device_sync_info: dict | None) -> bool | None:
    """Check server change using v4.7 device_syncs info.

    Parameters
    ----------
    device_sync_info:
        A single device sync record from the server's device_syncs array,
        or None if not available (v4.6 / no device registered).

    Returns
    -------
    bool | None
        True if server changed (is_current == False),
        False if server unchanged (is_current == True),
        None if indeterminate (no device_sync_info provided, or is_current is
        absent/None).
    """
    if device_sync_info is None:
        return None
    is_current = device_sync_info.get("is_current")
    if is_current is None:
        return None
    return not is_current


def determine_sync_action(
    local_changed: bool,
    server_save: dict | None,
    device_sync_info: dict | None = None,
    file_state: dict | None = None,
) -> str:
    """Determine the sync action combining local and server change detection.

    Parameters
    ----------
    local_changed:
        Whether the local file has changed since last sync (caller computes this).
    server_save:
        Server save metadata dict, or None if no server save exists.
    device_sync_info:
        v4.7 device sync record (has "is_current" key), or None for v4.6 fallback.
    file_state:
        Per-file sync state dict (used for v4.6 fallback via check_server_changes_fast).
        Only needed when device_sync_info is None.

    Returns
    -------
    str
        One of "skip", "upload", "download", "conflict", "initial_upload",
        "initial_download".
    """
    # No server save at all
    if server_save is None:
        return "initial_upload" if local_changed else "skip"

    # Server save exists — determine whether server has changed
    server_changed: bool

    # Priority 1: v4.7 device_sync_info
    v47_result = check_server_changed_v47(device_sync_info)
    if v47_result is not None:
        server_changed = v47_result
    else:
        # Priority 2: v4.6 fast-path using file_state
        if file_state is not None:
            v46_result = check_server_changes_fast(file_state, server_save)
            server_changed = v46_result if v46_result is not None else True
        else:
            # Priority 3: no info at all — safe default: assume server changed
            server_changed = True

    return determine_action(local_changed, server_changed)
