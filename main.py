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
from lib.firmware import FirmwareMixin
from lib.metadata import MetadataMixin
from lib.sgdb import SgdbMixin
from lib.downloads import DownloadMixin
from lib.sync import SyncMixin
from lib.save_sync import SaveSyncMixin
from lib import retrodeck_config


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
            "downloaded_bios": {},
            "retrodeck_home_path": "",
        }
        self._pending_sync = {}
        self._download_tasks = {}   # rom_id -> asyncio.Task
        self._download_queue = {}   # rom_id -> DownloadItem dict
        self._download_in_progress = set()  # rom_ids currently being processed
        self._metadata_cache = {}
        self._load_state()
        self._load_bios_registry()
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
        # ── RetroDECK path change detection ──
        self._detect_retrodeck_path_change()
        self.loop.create_task(self._poll_download_requests())
        decky.logger.info("RomM Sync plugin loaded")

    def _detect_retrodeck_path_change(self):
        """Check if RetroDECK home path changed since last run."""
        current_home = retrodeck_config.get_retrodeck_home()
        stored_home = self._state.get("retrodeck_home_path", "")

        if not current_home:
            return

        if stored_home == current_home:
            return

        if stored_home:
            old_home = stored_home
        else:
            # First run — check if files exist at the hardcoded fallback path
            # that differ from the actual RetroDECK config path
            fallback_home = os.path.join(decky.DECKY_USER_HOME, "retrodeck")
            if fallback_home != current_home and os.path.isdir(fallback_home):
                # Files may have been downloaded to fallback before we read config
                old_home = fallback_home
            else:
                # Genuine first run, no migration needed
                self._state["retrodeck_home_path"] = current_home
                self._save_state()
                return

        # Path changed — store both old and new, emit event
        self._state["retrodeck_home_path_previous"] = old_home
        self._state["retrodeck_home_path"] = current_home
        self._save_state()
        decky.logger.warning(
            f"RetroDECK home path changed: {old_home} -> {current_home}"
        )
        self.loop.create_task(
            decky.emit("retrodeck_path_changed", {
                "old_path": old_home,
                "new_path": current_home,
            })
        )

    async def migrate_retrodeck_files(self):
        """Move downloaded ROMs and BIOS files from old RetroDECK path to new path."""
        old_home = self._state.get("retrodeck_home_path_previous", "")
        new_home = self._state.get("retrodeck_home_path", "")

        if not old_home or not new_home or old_home == new_home:
            return {"success": False, "message": "No path migration needed"}

        import shutil

        roms_moved = 0
        bios_moved = 0
        errors = []

        # Migrate installed ROMs
        for rom_id, entry in list(self._state["installed_roms"].items()):
            file_path = entry.get("file_path", "")
            rom_dir = entry.get("rom_dir", "")

            for key in ("file_path", "rom_dir"):
                path = entry.get(key, "")
                if not path or not path.startswith(old_home):
                    continue
                new_path = new_home + path[len(old_home):]
                if os.path.exists(new_path):
                    decky.logger.warning(f"Migration skip (exists): {new_path}")
                    errors.append(f"Already exists: {os.path.basename(new_path)}")
                    continue
                if not os.path.exists(path):
                    decky.logger.warning(f"Migration skip (source missing): {path}")
                    continue
                try:
                    os.makedirs(os.path.dirname(new_path), exist_ok=True)
                    if os.path.isdir(path):
                        shutil.move(path, new_path)
                    else:
                        shutil.move(path, new_path)
                    entry[key] = new_path
                    if key == "file_path":
                        roms_moved += 1
                except Exception as e:
                    errors.append(f"{os.path.basename(path)}: {e}")
                    decky.logger.error(f"Migration failed for {path}: {e}")

        # Migrate downloaded BIOS files
        for file_name, bios_entry in list(self._state.get("downloaded_bios", {}).items()):
            file_path = bios_entry.get("file_path", "")
            if not file_path or not file_path.startswith(old_home):
                continue
            new_path = new_home + file_path[len(old_home):]
            if os.path.exists(new_path):
                decky.logger.warning(f"BIOS migration skip (exists): {new_path}")
                errors.append(f"Already exists: {file_name}")
                continue
            if not os.path.exists(file_path):
                decky.logger.warning(f"BIOS migration skip (source missing): {file_path}")
                continue
            try:
                os.makedirs(os.path.dirname(new_path), exist_ok=True)
                shutil.move(file_path, new_path)
                bios_entry["file_path"] = new_path
                bios_moved += 1
            except Exception as e:
                errors.append(f"{file_name}: {e}")
                decky.logger.error(f"BIOS migration failed for {file_path}: {e}")

        # Migrate untracked BIOS files (downloaded before state tracking)
        old_bios = os.path.join(old_home, "bios")
        new_bios = retrodeck_config.get_bios_path()
        if os.path.isdir(old_bios):
            for file_name, reg_entry in self._bios_files_index.items():
                # Only move files we recognize from the registry
                firmware_path = reg_entry.get("firmware_path", file_name)
                old_file = os.path.join(old_bios, firmware_path)
                new_file = os.path.join(new_bios, firmware_path)
                if not os.path.exists(old_file):
                    continue
                if os.path.exists(new_file):
                    continue
                # Skip if already tracked in downloaded_bios
                if file_name in self._state.get("downloaded_bios", {}):
                    continue
                try:
                    os.makedirs(os.path.dirname(new_file), exist_ok=True)
                    shutil.move(old_file, new_file)
                    bios_moved += 1
                    decky.logger.info(f"Migrated untracked BIOS: {old_file} -> {new_file}")
                except Exception as e:
                    errors.append(f"{file_name}: {e}")

        # Clear previous path marker after successful migration
        if not errors:
            self._state.pop("retrodeck_home_path_previous", None)
        self._save_state()

        msg = f"Migrated {roms_moved} ROM(s) and {bios_moved} BIOS file(s)"
        if errors:
            msg += f" ({len(errors)} error(s))"
        return {
            "success": len(errors) == 0,
            "message": msg,
            "roms_moved": roms_moved,
            "bios_moved": bios_moved,
            "errors": errors,
        }

    async def get_migration_status(self):
        """Return whether a RetroDECK path migration is pending and file counts."""
        old_home = self._state.get("retrodeck_home_path_previous", "")
        new_home = self._state.get("retrodeck_home_path", "")

        if not old_home or not new_home or old_home == new_home:
            return {"pending": False}

        # Count files that need migration
        roms_count = 0
        for entry in self._state.get("installed_roms", {}).values():
            for key in ("file_path", "rom_dir"):
                path = entry.get(key, "")
                if path and path.startswith(old_home) and key == "file_path":
                    roms_count += 1

        bios_count = 0
        for bios_entry in self._state.get("downloaded_bios", {}).values():
            file_path = bios_entry.get("file_path", "")
            if file_path and file_path.startswith(old_home):
                bios_count += 1

        # Count untracked BIOS files from registry
        old_bios = os.path.join(old_home, "bios")
        if os.path.isdir(old_bios):
            for file_name, reg_entry in self._bios_files_index.items():
                if file_name in self._state.get("downloaded_bios", {}):
                    continue
                firmware_path = reg_entry.get("firmware_path", file_name)
                old_file = os.path.join(old_bios, firmware_path)
                if os.path.exists(old_file):
                    bios_count += 1

        return {
            "pending": True,
            "old_path": old_home,
            "new_path": new_home,
            "roms_count": roms_count,
            "bios_count": bios_count,
        }

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
        """Return cached + lightweight data for a game."""
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

        # BIOS status
        platform_slug = entry.get("platform_slug", "")
        bios_status = None
        if platform_slug:
            try:
                bios = await self.check_platform_bios(platform_slug)
                if bios.get("needs_bios"):
                    bios_status = {
                        "platform_slug": platform_slug,
                        "total": bios.get("server_count", 0),
                        "downloaded": bios.get("local_count", 0),
                        "all_downloaded": bios.get("all_downloaded", False),
                        "required_count": bios.get("required_count"),
                        "required_downloaded": bios.get("required_downloaded"),
                    }
            except Exception as e:
                decky.logger.warning(f"BIOS status check failed for {platform_slug}: {e}")

        return {
            "found": True,
            "rom_id": rom_id,
            "rom_name": entry.get("name", ""),
            "platform_slug": platform_slug,
            "platform_name": entry.get("platform_name", ""),
            "installed": installed,
            "save_sync_enabled": save_sync_enabled,
            "save_status": save_status,
            "pending_conflicts": pending_conflicts,
            "metadata": metadata,
            "bios_status": bios_status,
        }
