"""Unified sync-action logic for save sync v2.

Extends the existing conflict detection (save_conflicts.py) with
RomM v4.7 device sync awareness (is_current flag from device_syncs).

Includes server-save matching: maps local files to their server counterparts
using tracked_save_id → filename → slot-fallback priority chain.

No I/O, no service/adapter/lib imports. Pure functions only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from domain.save_conflicts import check_server_changes_fast, determine_action

# ---------------------------------------------------------------------------
# Server-save matching
# ---------------------------------------------------------------------------


@dataclass
class MatchedSave:
    """A local file matched to a server save."""

    local_file: dict | None  # {"filename": str, "path": str} or None for server-only
    server_save: dict | None  # server save dict or None for local-only
    filename: str  # the LOCAL filename to use (not the server's timestamp name)
    match_method: str  # "tracked_id" | "filename" | "slot_fallback" | "local_only" | "server_only"


@dataclass
class MatchResult:
    """Result of matching local files to server saves."""

    matched: list[MatchedSave] = field(default_factory=list)
    matched_server_ids: set[int] = field(default_factory=set)
    new_tracked_ids: dict[str, int] = field(default_factory=dict)  # filename -> save_id to persist


def match_local_to_server_saves(
    local_files: list[dict],
    server_saves: list[dict],
    files_state: dict,
    active_slot: str | None,
    rom_name: str | None = None,
) -> MatchResult:
    """Match local save files to server saves.

    Priority per local file:
    1. tracked_save_id from state → exact server ID match
    2. Filename match → server has same filename
    3. Fallback: newest server save in active slot (recovery after state reset)

    Server-only saves (no local match) are included if they are the newest
    in their group AND not an older version of an already-matched save.

    Parameters
    ----------
    local_files:
        List of {"filename": str, "path": str} dicts from _find_save_files.
    server_saves:
        List of server save dicts from list_saves API.
    files_state:
        Per-file state dict from save_sync_state["saves"][rom_id]["files"].
    active_slot:
        The currently active slot for this game, or None.
    rom_name:
        The ROM base name (e.g. "Mario Golf - Advance Tour (USA)") for
        computing the expected local filename when downloading server-only saves.

    Returns
    -------
    MatchResult with matched pairs and bookkeeping sets.
    """
    result = MatchResult()

    # Build indexes
    server_by_id: dict[int, dict] = {}
    server_by_name: dict[str, dict] = {}
    for ss in server_saves:
        sid = ss.get("id")
        if sid is not None:
            server_by_id[sid] = ss
        fn = ss.get("file_name", "")
        if fn:
            server_by_name[fn] = ss

    local_by_name = {lf["filename"]: lf for lf in local_files}

    # --- Pass 1: Match each local file to a server save ---
    for lf in sorted(local_files, key=lambda x: x["filename"]):
        fn = lf["filename"]
        file_state = files_state.get(fn, {})
        server: dict | None = None
        method = "local_only"

        # Priority 1: tracked_save_id
        tracked_id = file_state.get("tracked_save_id")
        if tracked_id and tracked_id in server_by_id:
            server = server_by_id[tracked_id]
            method = "tracked_id"

        # Priority 2: filename match
        if not server:
            server = server_by_name.get(fn)
            if server:
                method = "filename"

        # Priority 3: fallback to newest in active slot
        if not server and server_saves:
            slot_candidates = [
                ss
                for ss in server_saves
                if ss.get("id") not in result.matched_server_ids
                and (ss.get("slot") == active_slot or (active_slot and ss.get("slot") is None))
            ]
            if slot_candidates:
                newest = max(slot_candidates, key=lambda s: s.get("updated_at", ""))
                server = newest
                method = "slot_fallback"
                result.new_tracked_ids[fn] = newest["id"]
                # Mark ALL candidates as matched (they are older versions)
                for sc in slot_candidates:
                    sc_id = sc.get("id")
                    if sc_id is not None:
                        result.matched_server_ids.add(sc_id)

        if server and server.get("id") is not None:
            result.matched_server_ids.add(server["id"])
            # Also mark older versions with same base name in same slot
            matched_ts = server.get("updated_at", "")
            matched_slot = server.get("slot")
            for ss in server_saves:
                ss_id = ss.get("id")
                if ss_id is not None and ss.get("slot") == matched_slot and ss.get("updated_at", "") <= matched_ts:
                    result.matched_server_ids.add(ss_id)

        result.matched.append(
            MatchedSave(
                local_file=lf,
                server_save=server,
                filename=fn,
                match_method=method,
            )
        )

    # --- Pass 2: Server-only saves (not matched by any local file) ---
    # Group by base name, pick newest per group, use local filename
    unmatched = [
        ss
        for ss in server_saves
        if ss.get("id") not in result.matched_server_ids and ss.get("file_name", "") not in local_by_name
    ]
    if unmatched:
        groups: dict[str, list[dict]] = {}
        for ss in unmatched:
            base = ss.get("file_name_no_tags") or ss.get("file_name", "unknown")
            groups.setdefault(base, []).append(ss)

        for _base, group in groups.items():
            newest = max(group, key=lambda s: s.get("updated_at", ""))
            # Compute local filename
            dl_filename = (
                (rom_name + "." + newest.get("file_extension", "srm"))
                if rom_name
                else (_base + "." + newest.get("file_extension", "srm"))
            )
            result.matched.append(
                MatchedSave(
                    local_file=None,
                    server_save=newest,
                    filename=dl_filename,
                    match_method="server_only",
                )
            )
            # Mark all in group
            for ss in group:
                ss_id = ss.get("id")
                if ss_id is not None:
                    result.matched_server_ids.add(ss_id)

    return result


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
