import os
import sys
import asyncio

plugin_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(plugin_dir, "py_modules"))
sys.path.insert(0, plugin_dir)

import decky

from lib.state import StateMixin
from lib.romm_client import RommClientMixin
from lib.steam_config import SteamConfigMixin
from lib.firmware import FirmwareMixin, BIOS_DEST_MAP
from lib.metadata import MetadataMixin
from lib.sgdb import SgdbMixin
from lib.downloads import DownloadMixin
from lib.sync import SyncMixin
from lib.save_sync import SaveSyncMixin


class Plugin(StateMixin, RommClientMixin, SgdbMixin, SteamConfigMixin, FirmwareMixin, MetadataMixin, DownloadMixin, SyncMixin, SaveSyncMixin):
    settings: dict
    loop: asyncio.AbstractEventLoop

    async def _main(self):
        self.loop = asyncio.get_event_loop()
        self._load_settings()
        self._sync_running = False
        self._sync_cancel = False
        self._sync_last_heartbeat = 0.0
        self._sync_progress = {
            "running": False,
            "phase": "",
            "current": 0,
            "total": 0,
            "message": "",
        }
        self._state = {
            "shortcut_registry": {},
            "installed_roms": {},
            "last_sync": None,
            "sync_stats": {"platforms": 0, "roms": 0},
        }
        self._pending_sync = {}
        self._download_tasks = {}   # rom_id -> asyncio.Task
        self._download_queue = {}   # rom_id -> DownloadItem dict
        self._download_in_progress = set()  # rom_ids currently being processed
        self._metadata_cache = {}
        self._load_state()
        self._load_metadata_cache()
        self._init_save_sync_state()
        self._load_save_sync_state()
        # ── Startup state healing ──
        self._prune_stale_installed_roms()      # lib/state.py
        self._prune_stale_registry()             # lib/state.py
        self._prune_orphaned_save_sync_state()   # lib/save_sync.py
        self._prune_orphaned_artwork_cache()     # lib/sgdb.py
        self._prune_orphaned_staging_artwork()   # lib/sync.py
        self._cleanup_leftover_tmp_files()       # lib/downloads.py
        self.loop.create_task(self._poll_download_requests())
        decky.logger.info("RomM Sync plugin loaded")

    async def _unload(self):
        if self._sync_running:
            self._sync_cancel = True
        # Cancel all active downloads
        for rom_id, task in list(self._download_tasks.items()):
            task.cancel()
        self._download_tasks.clear()
        decky.logger.info("RomM Sync plugin unloaded")

    async def test_connection(self):
        if not self.settings.get("romm_url"):
            return {"success": False, "message": "No server URL configured"}
        try:
            await self.loop.run_in_executor(
                None, self._romm_request, "/api/heartbeat"
            )
        except Exception as e:
            return {"success": False, "message": f"Cannot reach server: {e}"}
        try:
            await self.loop.run_in_executor(
                None, self._romm_request, "/api/platforms"
            )
        except Exception as e:
            return {"success": False, "message": f"Authentication failed: {e}"}
        return {"success": True, "message": "Connected to RomM"}

    async def save_settings(self, romm_url, romm_user, romm_pass, allow_insecure_ssl=None):
        try:
            self.settings["romm_url"] = romm_url
            self.settings["romm_user"] = romm_user
            # Only update password if user entered a new one (not the masked placeholder)
            if romm_pass and romm_pass != "••••":
                self.settings["romm_pass"] = romm_pass
            if allow_insecure_ssl is not None:
                self.settings["romm_allow_insecure_ssl"] = bool(allow_insecure_ssl)
            self._save_settings_to_disk()
            return {"success": True, "message": "Settings saved"}
        except Exception as e:
            decky.logger.error(f"Failed to save settings: {e}")
            return {"success": False, "message": f"Save failed: {e}"}

    async def frontend_log(self, level, message):
        """Log a frontend message. Respects log_level setting."""
        configured = self.settings.get("log_level", "warn")
        if self.LOG_LEVELS.get(level, 0) >= self.LOG_LEVELS.get(configured, 2):
            if level == "error":
                decky.logger.error(f"[FE] {message}")
            elif level == "warn":
                decky.logger.warning(f"[FE] {message}")
            else:
                decky.logger.info(f"[FE] {message}")

    async def debug_log(self, message):
        """Backward-compat wrapper: logs at debug level."""
        await self.frontend_log("debug", message)

    async def save_log_level(self, level):
        if level not in ("debug", "info", "warn", "error"):
            return {"success": False, "message": "Invalid log level"}
        self.settings["log_level"] = level
        self._save_settings_to_disk()
        return {"success": True}

    async def save_steam_input_setting(self, mode):
        if mode not in ("default", "force_on", "force_off"):
            return {"success": False, "message": f"Invalid mode: {mode}"}
        self.settings["steam_input_mode"] = mode
        self._save_settings_to_disk()
        return {"success": True}

    async def get_settings(self):
        has_credentials = bool(
            self.settings.get("romm_user") and self.settings.get("romm_pass")
        )
        return {
            "romm_url": self.settings.get("romm_url", ""),
            "romm_user": self.settings.get("romm_user", ""),
            "romm_pass_masked": "••••" if self.settings.get("romm_pass") else "",
            "has_credentials": has_credentials,
            "steam_input_mode": self.settings.get("steam_input_mode", "default"),
            "sgdb_api_key_masked": "••••" if self.settings.get("steamgriddb_api_key") else "",
            "retroarch_input_check": self._check_retroarch_input_driver(),
            "log_level": self.settings.get("log_level", "warn"),
            "romm_allow_insecure_ssl": self.settings.get("romm_allow_insecure_ssl", False),
        }

    async def get_cached_game_detail(self, app_id):
        """Return all locally-cached data for a game. No network calls."""
        app_id = int(app_id)

        # Reverse lookup: find rom_id by app_id in shortcut_registry
        rom_id = None
        entry = None
        for rid, reg in self._state["shortcut_registry"].items():
            if reg.get("app_id") == app_id:
                rom_id = int(rid)
                entry = reg
                break

        if rom_id is None:
            return {"found": False}

        rom_id_str = str(rom_id)

        # Installed status
        installed = rom_id_str in self._state["installed_roms"]

        # Save sync
        save_sync_enabled = self._save_sync_state.get("settings", {}).get(
            "save_sync_enabled", False
        )
        raw_save = self._save_sync_state.get("saves", {}).get(rom_id_str)
        save_status = None
        if raw_save:
            # Normalize files from dict {filename: {...}} to array [{filename, ...}]
            raw_files = raw_save.get("files", {})
            if isinstance(raw_files, dict):
                files_list = [
                    {"filename": fn,
                     "status": "synced" if fdata.get("last_sync_hash") else "unknown",
                     "last_sync_at": fdata.get("last_sync_at")}
                    for fn, fdata in raw_files.items()
                ]
            else:
                files_list = raw_files
            save_status = {
                "files": files_list,
                "last_sync_check_at": raw_save.get("last_sync_check_at"),
            }

        # Pending conflicts for this rom
        pending_conflicts = [
            c for c in self._save_sync_state.get("pending_conflicts", [])
            if c.get("rom_id") == rom_id
        ]

        # Metadata from cache
        metadata = self._metadata_cache.get(rom_id_str)

        return {
            "found": True,
            "rom_id": rom_id,
            "rom_name": entry.get("name", ""),
            "platform_slug": entry.get("platform_slug", ""),
            "platform_name": entry.get("platform_name", ""),
            "installed": installed,
            "save_sync_enabled": save_sync_enabled,
            "save_status": save_status,
            "pending_conflicts": pending_conflicts,
            "metadata": metadata,
            "bios_status": None,
        }
