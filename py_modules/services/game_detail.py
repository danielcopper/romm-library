"""GameDetailService — game detail page data aggregation.

Aggregates ROM registry data, save-sync state, firmware cache, metadata cache,
and achievement progress into a single response payload for the frontend game
detail page.  Uses callback injection (not direct service references) to stay
independent of other service modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain.bios import format_bios_status

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable


class GameDetailService:
    """Aggregates game detail page data from multiple state sources."""

    def __init__(
        self,
        *,
        state: dict,
        metadata_cache: dict,
        save_sync_state: dict,
        logger: logging.Logger,
        # Callbacks (cross-service, maintains independence)
        check_platform_bios_cached: Callable,
        check_platform_bios: Callable,
        get_ra_username: Callable,
        get_progress_cache_entry: Callable,
    ) -> None:
        self._state = state
        self._metadata_cache = metadata_cache
        self._save_sync_state = save_sync_state
        self._logger = logger
        self._check_platform_bios_cached = check_platform_bios_cached
        self._check_platform_bios = check_platform_bios
        self._get_ra_username = get_ra_username
        self._get_progress_cache_entry = get_progress_cache_entry

    def _resolve_rom_by_app_id(self, app_id: int) -> tuple[int | None, dict | None]:
        """Reverse lookup: find rom_id by app_id in shortcut_registry."""
        for rid, reg in self._state["shortcut_registry"].items():
            if reg.get("app_id") == app_id:
                return int(rid), reg
        return None, None

    def _resolve_rom_file(self, rom_id_str: str, entry: dict) -> str:
        """ROM filename from installed_roms or registry fs_name fallback."""
        rom_file = ""
        installed_rom = self._state["installed_roms"].get(rom_id_str, {})
        if installed_rom:
            rom_file = installed_rom.get("file_name", "")
        if not rom_file:
            rom_file = entry.get("fs_name", "")
        return rom_file

    async def get_cached_game_detail(self, app_id) -> dict:
        """Return cached + lightweight data for a game."""
        app_id = int(app_id)

        # Reverse lookup: find rom_id by app_id in shortcut_registry
        rom_id, entry = self._resolve_rom_by_app_id(app_id)

        if rom_id is None or entry is None:
            return {"found": False}

        rom_id_str = str(rom_id)

        # Installed status
        installed = rom_id_str in self._state["installed_roms"]

        # Save sync
        save_sync_enabled = self._save_sync_state.get("settings", {}).get("save_sync_enabled", False)
        raw_save = self._save_sync_state.get("saves", {}).get(rom_id_str)
        save_status = None
        if raw_save:
            # Normalize files from dict {filename: {...}} to array [{filename, ...}]
            raw_files = raw_save.get("files", {})
            if isinstance(raw_files, dict):
                files_list = [
                    {
                        "filename": fn,
                        "status": "synced" if fdata.get("last_sync_hash") else "unknown",
                        "last_sync_at": fdata.get("last_sync_at"),
                    }
                    for fn, fdata in raw_files.items()
                ]
            else:
                files_list = raw_files
            save_status = {
                "files": files_list,
                "last_sync_check_at": raw_save.get("last_sync_check_at"),
            }

        # Metadata from cache
        metadata = self._metadata_cache.get(rom_id_str)

        # ROM file name for per-game core overrides
        # Prefer installed_roms (set during download), fall back to registry (set during sync)
        rom_file = self._resolve_rom_file(rom_id_str, entry)

        platform_slug = entry.get("platform_slug", "")

        # BIOS status from firmware cache (no HTTP — cache-only read)
        bios_status = None
        if platform_slug:
            cached_bios = self._check_platform_bios_cached(platform_slug, rom_filename=rom_file or None)
            if cached_bios and cached_bios.get("needs_bios"):
                bios_status = format_bios_status(cached_bios, platform_slug)
                bios_status["cached_at"] = cached_bios.get("cached_at")

        # Achievement summary (for badge rendering)
        ra_id = entry.get("ra_id")
        achievement_summary = None
        if ra_id and self._get_ra_username():
            # Try cache first for quick badge rendering
            cached_progress = self._get_progress_cache_entry(rom_id_str)
            if cached_progress:
                achievement_summary = {
                    "earned": cached_progress.get("earned", 0),
                    "total": cached_progress.get("total", 0),
                    "earned_hardcore": cached_progress.get("earned_hardcore", 0),
                    "cached_at": cached_progress.get("cached_at"),
                }
            else:
                # Return None — frontend will fetch on demand
                achievement_summary = None

        return {
            "found": True,
            "rom_id": rom_id,
            "rom_name": entry.get("name", ""),
            "platform_slug": platform_slug,
            "platform_name": entry.get("platform_name", ""),
            "installed": installed,
            "save_sync_enabled": save_sync_enabled,
            "save_status": save_status,
            "metadata": metadata,
            "bios_status": bios_status,
            "rom_file": rom_file,
            "ra_id": ra_id,
            "achievement_summary": achievement_summary,
        }

    async def get_bios_status(self, rom_id) -> dict:
        """Return BIOS status for a ROM by looking up platform/rom_file from registry."""
        rom_id_str = str(rom_id)
        entry = self._state["shortcut_registry"].get(rom_id_str)
        if not entry:
            return {"bios_status": None}

        platform_slug = entry.get("platform_slug", "")
        if not platform_slug:
            return {"bios_status": None}

        # Resolve rom_file for per-game core override detection
        rom_file = self._resolve_rom_file(rom_id_str, entry)

        try:
            bios = await self._check_platform_bios(platform_slug, rom_filename=rom_file or None)
            if bios.get("needs_bios"):
                return {"bios_status": format_bios_status(bios, platform_slug)}
        except Exception as e:
            self._logger.warning(f"BIOS status check failed for {platform_slug}: {e}")

        return {"bios_status": None}
