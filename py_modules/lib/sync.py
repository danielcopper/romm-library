import os
import json
import asyncio
import base64
import time
import uuid
import urllib.parse
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any


class SyncState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    CANCELLING = "cancelling"

import decky

from lib.errors import classify_error

if TYPE_CHECKING:
    from typing import Callable, Optional, Protocol

    class _SyncDeps(Protocol):
        settings: dict
        _state: dict
        _sync_state: SyncState
        _sync_progress: dict
        _sync_last_heartbeat: float
        _pending_sync: dict
        _pending_delta: dict
        _metadata_cache: dict
        loop: asyncio.AbstractEventLoop
        def _romm_request(self, path: str) -> Any: ...
        def _romm_download(self, path: str, dest: str, progress_callback: Optional[Callable] = None) -> None: ...
        def _save_settings_to_disk(self) -> None: ...
        def _save_state(self) -> None: ...
        def _save_metadata_cache(self) -> None: ...
        def _log_debug(self, msg: str) -> None: ...
        def _extract_metadata(self, rom: dict) -> dict: ...
        def _grid_dir(self) -> Optional[str]: ...
        def _set_steam_input_config(self, app_ids: list, mode: str = "default") -> None: ...
        def _generate_app_id(self, exe: str, appname: str) -> int: ...
        def _generate_artwork_id(self, exe: str, appname: str) -> int: ...
        def _read_shortcuts(self) -> dict: ...
        def _write_shortcuts(self, data: dict) -> None: ...


class SyncMixin:
    async def get_platforms(self):
        try:
            platforms = await self.loop.run_in_executor(
                None, self._romm_request, "/api/platforms"
            )
        except Exception as e:
            decky.logger.error(f"Failed to fetch platforms: {e}")
            _code, _msg = classify_error(e)
            return {"success": False, "message": _msg, "error_code": _code}

        enabled = self.settings.get("enabled_platforms", {})
        result = []
        for p in platforms:
            rom_count = p.get("rom_count", 0)
            if rom_count == 0:
                continue
            pid = str(p["id"])
            result.append({
                "id": p["id"],
                "name": p.get("name", ""),
                "slug": p.get("slug", ""),
                "rom_count": rom_count,
                "sync_enabled": enabled.get(pid, len(enabled) == 0),
            })
        return {"success": True, "platforms": result}

    async def save_platform_sync(self, platform_id, enabled):
        pid = str(platform_id)
        self.settings["enabled_platforms"][pid] = bool(enabled)
        self._save_settings_to_disk()
        return {"success": True}

    async def set_all_platforms_sync(self, enabled):
        enabled = bool(enabled)
        try:
            platforms = await self.loop.run_in_executor(
                None, self._romm_request, "/api/platforms"
            )
        except Exception as e:
            decky.logger.error(f"Failed to fetch platforms: {e}")
            _code, _msg = classify_error(e)
            return {"success": False, "message": _msg, "error_code": _code}

        ep = {}
        for p in platforms:
            ep[str(p["id"])] = enabled
        self.settings["enabled_platforms"] = ep
        self._save_settings_to_disk()
        return {"success": True}

    async def start_sync(self):
        if self._sync_state != SyncState.IDLE:
            return {"success": False, "message": "Sync already in progress"}
        self._sync_state = SyncState.RUNNING
        self._sync_last_heartbeat = time.monotonic()
        self.loop.create_task(self._do_sync())
        return {"success": True, "message": "Sync started"}

    async def cancel_sync(self):
        if self._sync_state != SyncState.RUNNING:
            return {"success": True, "message": "No sync in progress"}
        self._sync_state = SyncState.CANCELLING
        return {"success": True, "message": "Sync cancelling..."}

    async def get_sync_progress(self):
        return self._sync_progress

    async def sync_heartbeat(self):
        """Called by frontend during shortcut application to keep safety timeout alive."""
        self._sync_last_heartbeat = time.monotonic()
        return {"success": True}

    async def sync_preview(self):
        if self._sync_state != SyncState.IDLE:
            return {"success": False, "message": "Sync already in progress"}
        self._sync_state = SyncState.RUNNING
        self._sync_last_heartbeat = time.monotonic()
        try:
            all_roms, shortcuts_data, platforms = await self._fetch_and_prepare()
            platform_names = {p.get("name") for p in platforms}
            new, changed, unchanged_ids, stale, disabled_count = \
                self._classify_roms(shortcuts_data, platform_names)

            # Build rom lookup for artwork download during apply
            roms_by_id = {r["id"]: r for r in all_roms}
            delta_rom_ids = {sd["rom_id"] for sd in new + changed}
            delta_roms = [roms_by_id[rid] for rid in delta_rom_ids if rid in roms_by_id]

            preview_id = str(uuid.uuid4())
            self._pending_delta = {
                "preview_id": preview_id,
                "new": new,
                "changed": changed,
                "unchanged_ids": unchanged_ids,
                "remove_rom_ids": stale,
                "all_shortcuts": {sd["rom_id"]: sd for sd in shortcuts_data},
                "delta_roms": delta_roms,
                "platforms_count": len(platforms),
                "total_roms": len(all_roms),
            }

            await self._emit_progress("done", message="Preview ready", running=False)

            return {
                "success": True,
                "summary": {
                    "new_count": len(new),
                    "changed_count": len(changed),
                    "unchanged_count": len(unchanged_ids),
                    "remove_count": len(stale),
                    "disabled_platform_remove_count": disabled_count,
                },
                "new_names": [s["name"] for s in new[:10]],
                "changed_names": [s["name"] for s in changed[:10]],
                "preview_id": preview_id,
            }
        except asyncio.CancelledError:
            await self._finish_sync("Sync cancelled")
            return {"success": False, "message": "Sync cancelled"}
        except Exception as e:
            import traceback
            decky.logger.error(f"Sync preview failed: {e}\n{traceback.format_exc()}")
            _code, _msg = classify_error(e)
            await self._emit_progress("error", message=_msg, running=False)
            return {"success": False, "message": _msg, "error_code": _code}
        finally:
            self._sync_state = SyncState.IDLE

    async def sync_apply_delta(self, preview_id):
        if not self._pending_delta or self._pending_delta["preview_id"] != preview_id:
            return {"success": False, "message": "Preview expired, please re-sync",
                    "error_code": "stale_preview"}
        delta = self._pending_delta
        self._pending_delta = None
        self._sync_state = SyncState.RUNNING
        self._sync_last_heartbeat = time.monotonic()

        # Build collection_platform_app_ids from registry (unchanged)
        registry = self._state["shortcut_registry"]
        collection_map = {}
        for rid in delta["unchanged_ids"]:
            reg = registry.get(str(rid), {})
            pname = reg.get("platform_name", "")
            app_id = reg.get("app_id")
            if pname and app_id:
                collection_map.setdefault(pname, []).append(app_id)

        # Calculate apply step plan
        delta_roms = delta.get("delta_roms", [])
        has_artwork = len(delta_roms) > 0
        has_shortcuts = len(delta["new"]) + len(delta["changed"]) > 0
        has_removals = len(delta["remove_rom_ids"]) > 0
        # Collections step is always counted (unchanged shortcuts need collection updates too)

        apply_steps = []
        if has_artwork:
            apply_steps.append("artwork")
        if has_shortcuts:
            apply_steps.append("shortcuts")
        if has_removals:
            apply_steps.append("removals")
        apply_steps.append("collections")
        total_steps = len(apply_steps)
        current_step = 0

        # Step: Download artwork
        if has_artwork:
            current_step += 1
            await self._emit_progress("applying", total=len(delta_roms),
                message=f"Downloading artwork 0/{len(delta_roms)}",
                step=current_step, total_steps=total_steps)
            cover_paths = await self._download_artwork(
                delta_roms, progress_step=current_step, progress_total_steps=total_steps)
            for sd in delta["new"] + delta["changed"]:
                sd["cover_path"] = cover_paths.get(sd["rom_id"], "")

        # Populate _pending_sync for report_sync_results and get_artwork_base64
        self._pending_sync = delta["all_shortcuts"]

        # Update sync_stats
        self._state["sync_stats"] = {
            "platforms": delta["platforms_count"],
            "roms": delta["total_roms"],
        }
        self._save_state()

        # Figure out which step the frontend starts at
        next_step = current_step + 1

        total_changes = len(delta["new"]) + len(delta["changed"])
        await self._emit_progress("applying", total=total_changes,
            message=f"Applying shortcuts 0/{total_changes}",
            step=next_step, total_steps=total_steps)

        # Emit delta with step plan for frontend
        await decky.emit("sync_apply", {
            "shortcuts": delta["new"],
            "changed_shortcuts": delta["changed"],
            "remove_rom_ids": delta["remove_rom_ids"],
            "collection_platform_app_ids": collection_map,
            "next_step": next_step,
            "total_steps": total_steps,
        })

        decky.logger.info(
            f"Delta sync emitted: {len(delta['new'])} new, {len(delta['changed'])} changed, "
            f"{len(delta['remove_rom_ids'])} removed"
        )

        # Heartbeat safety timeout
        self._sync_last_heartbeat = time.monotonic()
        heartbeat_timeout_sec = 30

        async def _safety_timeout():
            while self._sync_progress.get("running"):
                await asyncio.sleep(10)
                elapsed = time.monotonic() - self._sync_last_heartbeat
                if elapsed > heartbeat_timeout_sec:
                    decky.logger.warning(
                        f"Sync safety timeout: no heartbeat for {elapsed:.0f}s"
                    )
                    stats = self._state.get("sync_stats", {})
                    await self._emit_progress("done",
                        current=stats.get("roms", 0),
                        total=stats.get("roms", 0),
                        message=f"Sync complete: {stats.get('roms', 0)} games from {stats.get('platforms', 0)} platforms",
                        running=False)
                    self._sync_state = SyncState.IDLE
                    return
        self.loop.create_task(_safety_timeout())

        return {"success": True, "message": "Applying changes"}

    async def sync_cancel_preview(self):
        self._pending_delta = None
        return {"success": True}

    async def _emit_progress(self, phase, current=0, total=0, message="", running=True, step=0, total_steps=0):
        """Update _sync_progress and emit sync_progress event to frontend."""
        self._sync_progress = {
            "running": running,
            "phase": phase,
            "current": current,
            "total": total,
            "message": message,
            "step": step,
            "totalSteps": total_steps,
        }
        await decky.emit("sync_progress", self._sync_progress)

    def _classify_roms(self, shortcuts_data, fetched_platform_names):
        """Classify each ROM as new/changed/unchanged/stale."""
        registry = self._state["shortcut_registry"]
        new, changed, unchanged_ids = [], [], []

        for sd in shortcuts_data:
            reg = registry.get(str(sd["rom_id"]))
            if not reg or not reg.get("app_id"):
                new.append(sd)
            elif (reg.get("name") != sd["name"] or
                  reg.get("platform_name") != sd.get("platform_name") or
                  reg.get("platform_slug") != sd.get("platform_slug") or
                  reg.get("fs_name") != sd.get("fs_name", "")):
                sd["existing_app_id"] = reg["app_id"]
                changed.append(sd)
            else:
                unchanged_ids.append(sd["rom_id"])

        # Stale: in registry but not in fetched set
        current_ids = {sd["rom_id"] for sd in shortcuts_data}
        stale = [int(rid) for rid in registry if int(rid) not in current_ids]

        # Classify stale by disabled platform
        disabled_count = sum(
            1 for rid in stale
            if registry.get(str(rid), {}).get("platform_name") not in fetched_platform_names
        )

        return new, changed, unchanged_ids, stale, disabled_count

    async def _fetch_and_prepare(self):
        """Fetch platforms + ROMs, prepare shortcut data.
        Returns (all_roms, shortcuts_data, platforms) or raises on cancel/error.
        Artwork download is deferred to the apply phase.
        Uses updated_after on subsequent syncs to skip unchanged platforms.
        Emits sync_progress events throughout."""

        # Phase 1: Fetch platforms
        await self._emit_progress("platforms", message="Fetching platforms...")

        platforms = await self.loop.run_in_executor(
            None, self._romm_request, "/api/platforms"
        )

        if self._sync_state == SyncState.CANCELLING:
            raise asyncio.CancelledError("Sync cancelled")

        # Filter platforms by enabled_platforms setting
        enabled = self.settings.get("enabled_platforms", {})
        no_prefs = len(enabled) == 0
        decky.logger.info(f"Platform filter: {len(enabled)} prefs saved, no_prefs={no_prefs}")
        decky.logger.info(f"Enabled platforms: {[k for k,v in enabled.items() if v]}")
        platforms = [
            p for p in platforms
            if enabled.get(str(p["id"]), no_prefs)
        ]
        decky.logger.info(f"Syncing {len(platforms)} platforms: {[p['name'] for p in platforms]}")

        # Phase 2: Fetch ROMs per platform (incremental if possible)
        await self._emit_progress("roms", message="Fetching ROMs...")

        last_sync = self._state.get("last_sync")
        registry = self._state.get("shortcut_registry", {})

        all_roms = []
        total_platforms = len(platforms)
        for pi, platform in enumerate(platforms, 1):
            if self._sync_state == SyncState.CANCELLING:
                raise asyncio.CancelledError("Sync cancelled")

            platform_id = platform["id"]
            platform_name = platform.get("name", platform.get("display_name", "Unknown"))
            platform_slug = platform.get("slug", "")
            offset = 0
            limit = 50

            # Count how many ROMs we have in registry for this platform
            registry_count = sum(
                1 for e in registry.values()
                if e.get("platform_name") == platform_name
            )

            # Try incremental fetch if we have a last_sync timestamp
            if last_sync and registry_count > 0:
                updated_after = urllib.parse.quote(last_sync)
                try:
                    delta_resp = await self.loop.run_in_executor(
                        None,
                        self._romm_request,
                        f"/api/roms?platform_ids={platform_id}&limit=1&offset=0&updated_after={updated_after}",
                    )
                    server_total = delta_resp.get("total", 0) if isinstance(delta_resp, dict) else 0

                    # Also check total ROM count without updated_after (for stale detection)
                    count_resp = await self.loop.run_in_executor(
                        None,
                        self._romm_request,
                        f"/api/roms?platform_ids={platform_id}&limit=1&offset=0",
                    )
                    platform_total = count_resp.get("total", 0) if isinstance(count_resp, dict) else 0

                    if server_total == 0 and platform_total == registry_count:
                        # Nothing changed, nothing deleted — reconstruct from registry
                        decky.logger.info(
                            f"Skipping {platform_name}: {registry_count} ROMs unchanged"
                        )
                        for rid, entry in registry.items():
                            if entry.get("platform_name") == platform_name:
                                all_roms.append({
                                    "id": int(rid),
                                    "name": entry["name"],
                                    "fs_name": entry.get("fs_name", ""),
                                    "platform_name": platform_name,
                                    "platform_slug": platform_slug,
                                    "platform_display_name": platform_name,
                                    "igdb_id": entry.get("igdb_id"),
                                    "sgdb_id": entry.get("sgdb_id"),
                                    "ra_id": entry.get("ra_id"),
                                })
                        await self._emit_progress("roms", current=len(all_roms),
                            message=f"{platform_name} unchanged ({pi}/{total_platforms})")
                        continue
                    else:
                        decky.logger.info(
                            f"{platform_name}: {server_total} updated, "
                            f"server={platform_total} vs registry={registry_count} — full fetch"
                        )
                except Exception as e:
                    decky.logger.warning(
                        f"Incremental check failed for {platform_name}, falling back to full fetch: {e}"
                    )

            # Full fetch for this platform
            await self._emit_progress("roms", current=len(all_roms),
                message=f"Fetching {platform_name}... {len(all_roms)} found ({pi}/{total_platforms})")

            while True:
                if self._sync_state == SyncState.CANCELLING:
                    raise asyncio.CancelledError("Sync cancelled")

                try:
                    roms = await self.loop.run_in_executor(
                        None,
                        self._romm_request,
                        f"/api/roms?platform_ids={platform_id}&limit={limit}&offset={offset}",
                    )
                except Exception as e:
                    decky.logger.error(
                        f"Failed to fetch ROMs for platform {platform_name}: {e}"
                    )
                    break

                if isinstance(roms, dict):
                    rom_list = roms.get("items", [])
                else:
                    rom_list = roms

                for rom in rom_list:
                    rom.pop("files", None)
                    rom["platform_name"] = platform_name
                    rom["platform_slug"] = platform_slug

                all_roms.extend(rom_list)
                await self._emit_progress("roms", current=len(all_roms),
                    message=f"Fetching {platform_name}... {len(all_roms)} found ({pi}/{total_platforms})")

                if len(rom_list) < limit:
                    break
                offset += limit

        if self._sync_state == SyncState.CANCELLING:
            raise asyncio.CancelledError("Sync cancelled")

        decky.logger.info(
            f"Fetched {len(all_roms)} ROMs from {len(platforms)} platforms"
        )

        # Phase 3: Prepare shortcut data
        exe = os.path.join(decky.DECKY_PLUGIN_DIR, "bin", "romm-launcher")
        start_dir = os.path.join(decky.DECKY_PLUGIN_DIR, "bin")

        shortcuts_data = []
        for i, rom in enumerate(all_roms):
            shortcuts_data.append({
                "rom_id": rom["id"],
                "name": rom["name"],
                "fs_name": rom.get("fs_name", ""),
                "exe": exe,
                "start_dir": start_dir,
                "launch_options": f"romm:{rom['id']}",
                "platform_name": rom.get("platform_name", "Unknown"),
                "platform_slug": rom.get("platform_slug", ""),
                "igdb_id": rom.get("igdb_id"),
                "sgdb_id": rom.get("sgdb_id"),
                "ra_id": rom.get("ra_id"),
                "cover_path": "",
            })

        if self._sync_state == SyncState.CANCELLING:
            raise asyncio.CancelledError("Sync cancelled")

        # Cache metadata from sync response
        for rom in all_roms:
            rom_id_str = str(rom["id"])
            self._metadata_cache[rom_id_str] = self._extract_metadata(rom)
        self._save_metadata_cache()
        self._log_debug(f"Metadata cached for {len(all_roms)} ROMs")

        return all_roms, shortcuts_data, platforms

    async def _do_sync(self):
        try:
            try:
                all_roms, shortcuts_data, platforms = await self._fetch_and_prepare()
            except asyncio.CancelledError:
                await self._finish_sync("Sync cancelled")
                return
            except Exception as e:
                decky.logger.error(f"Failed to fetch platforms: {e}")
                _code, _msg = classify_error(e)
                await self._emit_progress("error", message=_msg, running=False)
                self._sync_state = SyncState.IDLE
                return

            # Calculate step plan for full sync
            has_artwork = len(all_roms) > 0
            has_shortcuts = len(shortcuts_data) > 0
            full_steps = []
            if has_artwork:
                full_steps.append("artwork")
            if has_shortcuts:
                full_steps.append("shortcuts")
            full_steps.append("collections")
            full_total_steps = len(full_steps)
            full_current_step = 0

            if has_artwork:
                full_current_step += 1
                await self._emit_progress("applying", total=len(all_roms),
                    message=f"Downloading artwork 0/{len(all_roms)}",
                    step=full_current_step, total_steps=full_total_steps)
                cover_paths = await self._download_artwork(
                    all_roms, progress_step=full_current_step,
                    progress_total_steps=full_total_steps)
            else:
                cover_paths = {}

            if self._sync_state == SyncState.CANCELLING:
                await self._finish_sync("Sync cancelled")
                return

            for sd in shortcuts_data:
                sd["cover_path"] = cover_paths.get(sd["rom_id"], "")

            # Determine stale rom_ids by comparing current sync with registry
            current_rom_ids = {r["id"] for r in all_roms}
            stale_rom_ids = [
                int(rid) for rid in self._state["shortcut_registry"]
                if int(rid) not in current_rom_ids
            ]

            # Emit sync_apply for frontend to process via SteamClient
            next_step = full_current_step + 1
            await self._emit_progress("applying", total=len(shortcuts_data),
                message=f"Applying shortcuts 0/{len(shortcuts_data)}",
                step=next_step, total_steps=full_total_steps)

            # Save sync stats (registry updated by report_sync_results)
            self._state["sync_stats"] = {
                "platforms": len(platforms),
                "roms": len(all_roms),
            }
            self._save_state()

            # Store pending data for report_sync_results to reference
            self._pending_sync = {sd["rom_id"]: sd for sd in shortcuts_data}

            await decky.emit("sync_apply", {
                "shortcuts": shortcuts_data,
                "remove_rom_ids": stale_rom_ids,
                "next_step": next_step,
                "total_steps": full_total_steps,
            })

            decky.logger.info(
                f"Sync data emitted: {len(shortcuts_data)} shortcuts, "
                f"{len(stale_rom_ids)} stale"
            )
        except Exception as e:
            import traceback
            decky.logger.error(f"Sync failed: {e}\n{traceback.format_exc()}")
            _code, _msg = classify_error(e)
            self._sync_progress = {
                "running": False,
                "phase": "error",
                "current": 0,
                "total": 0,
                "message": f"Sync failed \u2014 {_msg}",
            }
            self.loop.create_task(decky.emit("sync_progress", self._sync_progress))
        finally:
            self._sync_state = SyncState.IDLE
            if self._sync_progress.get("phase") == "error":
                pass
            elif self._sync_progress.get("running"):
                self._sync_last_heartbeat = time.monotonic()
                heartbeat_timeout_sec = 30

                async def _safety_timeout():
                    while self._sync_progress.get("running"):
                        await asyncio.sleep(10)
                        elapsed = time.monotonic() - self._sync_last_heartbeat
                        if elapsed > heartbeat_timeout_sec:
                            decky.logger.warning(
                                f"Sync safety timeout: no heartbeat for {elapsed:.0f}s"
                            )
                            stats = self._state.get("sync_stats", {})
                            await self._emit_progress("done",
                                current=stats.get("roms", 0),
                                total=stats.get("roms", 0),
                                message=f"Sync complete: {stats.get('roms', 0)} games from {stats.get('platforms', 0)} platforms",
                                running=False)
                            return
                self.loop.create_task(_safety_timeout())

    async def _finish_sync(self, message):
        self._sync_progress = {
            "running": False,
            "phase": "cancelled",
            "current": self._sync_progress.get("current", 0),
            "total": self._sync_progress.get("total", 0),
            "message": message,
        }
        await decky.emit("sync_progress", self._sync_progress)
        self._sync_state = SyncState.IDLE
        decky.logger.info(message)

    def _report_sync_results_io(self, rom_id_to_app_id, removed_rom_ids):
        """Sync helper for report_sync_results — artwork renames, VDF writes, state save in executor."""
        grid = self._grid_dir()

        # Update registry with new mappings from frontend
        for rom_id_str, app_id in rom_id_to_app_id.items():
            pending = self._pending_sync.get(int(rom_id_str), {})
            cover_path = pending.get("cover_path", "")

            # Rename staged artwork to final Steam app_id filename
            if grid and cover_path:
                final_path = os.path.join(grid, f"{app_id}p.png")
                if cover_path != final_path and os.path.exists(cover_path):
                    try:
                        os.replace(cover_path, final_path)
                        cover_path = final_path
                    except OSError as e:
                        decky.logger.warning(
                            f"Failed to rename artwork for rom {rom_id_str}: {e}"
                        )
                elif os.path.exists(final_path):
                    cover_path = final_path

            registry_entry = {
                "app_id": app_id,
                "name": pending.get("name", ""),
                "fs_name": pending.get("fs_name", ""),
                "platform_name": pending.get("platform_name", ""),
                "platform_slug": pending.get("platform_slug", ""),
                "cover_path": cover_path,
            }
            for meta_key in ("igdb_id", "sgdb_id", "ra_id"):
                if pending.get(meta_key):
                    registry_entry[meta_key] = pending[meta_key]
            self._state["shortcut_registry"][rom_id_str] = registry_entry

        # Remove stale entries
        for rom_id in removed_rom_ids:
            self._state["shortcut_registry"].pop(str(rom_id), None)

        # Apply Steam Input mode for new shortcuts
        steam_input_mode = self.settings.get("steam_input_mode", "default")
        if steam_input_mode != "default" and rom_id_to_app_id:
            try:
                self._set_steam_input_config(
                    [int(aid) for aid in rom_id_to_app_id.values()], mode=steam_input_mode
                )
            except Exception as e:
                decky.logger.error(f"Failed to set Steam Input config: {e}")

        # Update timestamp and save
        self._state["last_sync"] = datetime.now(timezone.utc).isoformat()
        self._save_state()
        self._pending_sync = {}

        # Rebuild platform_app_ids from registry
        platform_app_ids = {}
        for entry in self._state["shortcut_registry"].values():
            pname = entry.get("platform_name", "Unknown")
            platform_app_ids.setdefault(pname, []).append(entry.get("app_id"))

        return platform_app_ids

    async def report_sync_results(self, rom_id_to_app_id, removed_rom_ids, cancelled=False):
        """Called by frontend after applying shortcuts via SteamClient."""
        platform_app_ids = await self.loop.run_in_executor(
            None, self._report_sync_results_io, rom_id_to_app_id, removed_rom_ids
        )

        total = len(self._state["shortcut_registry"])
        processed = len(rom_id_to_app_id)

        if cancelled:
            await decky.emit("sync_complete", {
                "platform_app_ids": platform_app_ids,
                "total_games": processed,
                "cancelled": True,
            })
            await self._emit_progress("done", current=processed, total=total,
                message=f"Sync cancelled: {processed} of {total} games processed",
                running=False)
            decky.logger.info(f"Sync cancelled: {processed}/{total} games processed")
        else:
            await decky.emit("sync_complete", {
                "platform_app_ids": platform_app_ids,
                "total_games": total,
            })
            await self._emit_progress("done", current=total, total=total,
                message=f"Sync complete: {total} games from {len(platform_app_ids)} platforms",
                running=False)
            decky.logger.info(f"Sync results reported: {total} games")
        self._sync_state = SyncState.IDLE
        return {"success": True}

    # Deprecated: VDF-based shortcut creation (replaced by frontend SteamClient API)
    def _create_shortcuts(self, all_roms):
        data = self._read_shortcuts()
        shortcuts = data.get("shortcuts", {})

        # Index existing RomM shortcuts by rom_id
        existing_romm = {}
        for key, entry in shortcuts.items():
            launch_opts = entry.get("LaunchOptions", "")
            if isinstance(launch_opts, str) and launch_opts.startswith("romm:"):
                try:
                    rom_id = int(launch_opts.split(":", 1)[1])
                    existing_romm[rom_id] = key
                except (ValueError, IndexError):
                    pass

        exe = os.path.join(decky.DECKY_PLUGIN_DIR, "bin", "romm-launcher")
        start_dir = os.path.dirname(exe)
        current_rom_ids = set()
        platform_apps = {}

        # Find the next available numeric key
        if shortcuts:
            next_key = max(int(k) for k in shortcuts) + 1
        else:
            next_key = 0

        for rom in all_roms:
            rom_id = rom["id"]
            current_rom_ids.add(rom_id)
            app_id = self._generate_app_id(exe, rom["name"])
            artwork_id = self._generate_artwork_id(exe, rom["name"])
            platform_name = rom.get(
                "platform_name",
                rom.get("platform_display_name", "Unknown"),
            )

            entry = {
                "appid": app_id,
                "AppName": rom["name"],
                "Exe": f'"{exe}"',
                "StartDir": f'"{start_dir}"',
                "LaunchOptions": f"romm:{rom_id}",
                "icon": "",
                "ShortcutPath": "",
                "IsHidden": 0,
                "AllowDesktopConfig": 1,
                "AllowOverlay": 1,
                "OpenVR": 0,
                "Devkit": 0,
                "DevkitGameID": "",
                "DevkitOverrideAppID": 0,
                "LastPlayTime": 0,
                "tags": {"0": "RomM", "1": platform_name},
            }

            if rom_id in existing_romm:
                shortcuts[existing_romm[rom_id]] = entry
            else:
                shortcuts[str(next_key)] = entry
                next_key += 1

            # Track for platform_apps return and state
            platform_apps.setdefault(platform_name, []).append(app_id)
            self._state["shortcut_registry"][str(rom_id)] = {
                "app_id": app_id,
                "artwork_id": artwork_id,
                "name": rom["name"],
            }

        # Remove stale RomM shortcuts
        for rom_id, key in existing_romm.items():
            if rom_id not in current_rom_ids:
                del shortcuts[key]
                self._state["shortcut_registry"].pop(str(rom_id), None)

        data["shortcuts"] = shortcuts
        self._write_shortcuts(data)
        decky.logger.info(f"Wrote {len(current_rom_ids)} shortcuts")
        return platform_apps

    async def _download_artwork(self, all_roms, progress_step=4, progress_total_steps=6):
        """Download cover artwork to staging filenames (romm_{rom_id}_cover.png).

        Decouples download from the final Steam app_id, which isn't known until
        after AddShortcut. report_sync_results() renames to {app_id}p.png.
        Returns dict of rom_id -> local cover path.
        """
        cover_paths = {}
        grid = self._grid_dir()
        if not grid:
            decky.logger.warning("Cannot find grid directory, skipping artwork")
            return cover_paths

        total = len(all_roms)

        for i, rom in enumerate(all_roms):
            if self._sync_state == SyncState.CANCELLING:
                return cover_paths

            await self._emit_progress("applying", current=i + 1, total=total,
                message=f"Downloading artwork {i + 1}/{total}",
                step=progress_step, total_steps=progress_total_steps)

            # Determine cover URL from ROM data
            cover_url = rom.get("path_cover_large") or rom.get("path_cover_small")
            if not cover_url:
                continue

            rom_id = rom["id"]
            staging = os.path.join(grid, f"romm_{rom_id}_cover.png")

            # If already synced and final artwork exists, skip download
            reg = self._state["shortcut_registry"].get(str(rom_id))
            if reg and reg.get("app_id"):
                final = os.path.join(grid, f"{reg['app_id']}p.png")
                if os.path.exists(final):
                    cover_paths[rom_id] = final
                    continue

            # If staging file already exists (e.g. retry), skip download
            if os.path.exists(staging):
                cover_paths[rom_id] = staging
                continue

            try:
                await self.loop.run_in_executor(
                    None, self._romm_download, cover_url, staging
                )
                cover_paths[rom_id] = staging
            except Exception as e:
                decky.logger.warning(
                    f"Failed to download artwork for {rom['name']}: {e}"
                )

            # sgdb_id is now stored directly from RomM during sync (no SGDB API call needed)

        return cover_paths

    async def get_registry_platforms(self):
        """Return platforms from the shortcut registry (works offline, no RomM API call)."""
        platforms = {}
        for rom_id, entry in self._state["shortcut_registry"].items():
            pname = entry.get("platform_name", "Unknown")
            slug = entry.get("platform_slug", "")
            platforms.setdefault(pname, {"count": 0, "slug": slug})
            platforms[pname]["count"] += 1
        return {"platforms": [{"name": k, "slug": v["slug"], "count": v["count"]} for k, v in sorted(platforms.items())]}

    async def remove_platform_shortcuts(self, platform_slug):
        """Return app_ids and rom_ids for a platform for the frontend to remove via SteamClient."""
        try:
            # Try registry first (works offline)
            platform_name = None
            for entry in self._state["shortcut_registry"].values():
                if entry.get("platform_slug") == platform_slug:
                    platform_name = entry.get("platform_name")
                    break

            # Fall back to API if slug not in registry
            if not platform_name:
                platforms = await self.loop.run_in_executor(
                    None, self._romm_request, "/api/platforms"
                )
                for p in platforms:
                    if p.get("slug") == platform_slug:
                        platform_name = p.get("name", "")
                        break

            if not platform_name:
                return {
                    "success": False,
                    "message": f"Platform '{platform_slug}' not found",
                    "app_ids": [],
                    "rom_ids": [],
                }

            app_ids = []
            rom_ids = []
            for rom_id, entry in self._state["shortcut_registry"].items():
                if entry.get("platform_name") == platform_name:
                    if "app_id" in entry:
                        app_ids.append(entry["app_id"])
                    rom_ids.append(rom_id)

            return {
                "success": True,
                "app_ids": app_ids,
                "rom_ids": rom_ids,
                "platform_name": platform_name,
            }
        except Exception as e:
            decky.logger.error(f"Failed to get platform shortcuts: {e}")
            return {
                "success": False,
                "message": f"Failed: {e}",
                "app_ids": [],
                "rom_ids": [],
            }

    async def remove_all_shortcuts(self):
        """Return app_ids and rom_ids for the frontend to remove via SteamClient."""
        registry = self._state.get("shortcut_registry", {})
        app_ids = [entry["app_id"] for entry in registry.values() if "app_id" in entry]
        rom_ids = list(registry.keys())
        return {"success": True, "app_ids": app_ids, "rom_ids": rom_ids}

    def _report_removal_results_io(self, removed_rom_ids):
        """Sync helper for report_removal_results — file deletions, VDF writes, state save in executor."""
        # Clean up Steam Input config for removed shortcuts (always reset to default)
        removed_app_ids = []
        for rom_id in removed_rom_ids:
            entry = self._state["shortcut_registry"].get(str(rom_id))
            if entry and entry.get("app_id"):
                removed_app_ids.append(entry["app_id"])
        if removed_app_ids:
            try:
                self._set_steam_input_config(removed_app_ids, mode="default")
            except Exception as e:
                decky.logger.error(f"Failed to clean up Steam Input config: {e}")

        grid = self._grid_dir()
        for rom_id in removed_rom_ids:
            entry = self._state["shortcut_registry"].pop(str(rom_id), None)
            if entry and grid:
                removed = False
                # Try cover_path first (stores the final renamed path)
                cover_path = entry.get("cover_path", "")
                if cover_path and os.path.exists(cover_path):
                    os.remove(cover_path)
                    removed = True
                # Try {app_id}p.png (the standard Steam grid filename)
                if not removed and entry.get("app_id"):
                    app_path = os.path.join(grid, f"{entry['app_id']}p.png")
                    if os.path.exists(app_path):
                        os.remove(app_path)
                        removed = True
                # Fallback: legacy artwork_id format
                if not removed:
                    artwork_id = entry.get("artwork_id")
                    if artwork_id:
                        art_path = os.path.join(grid, f"{artwork_id}p.png")
                        if os.path.exists(art_path):
                            os.remove(art_path)
                # Clean up any leftover staging file
                staging = os.path.join(grid, f"romm_{rom_id}_cover.png")
                if os.path.exists(staging):
                    os.remove(staging)

        # Update sync_stats to reflect current registry
        registry = self._state.get("shortcut_registry", {})
        platforms = set(e.get("platform_name", "") for e in registry.values())
        self._state["sync_stats"] = {
            "platforms": len(platforms),
            "roms": len(registry),
        }
        self._save_state()

    async def report_removal_results(self, removed_rom_ids):
        """Called by frontend after removing shortcuts via SteamClient."""
        await self.loop.run_in_executor(
            None, self._report_removal_results_io, removed_rom_ids
        )
        return {"success": True, "message": f"Removed {len(removed_rom_ids)} shortcuts"}

    async def get_artwork_base64(self, rom_id):
        """Return base64-encoded cover artwork for a single ROM (callable from frontend)."""
        rom_id = int(rom_id)
        grid = self._grid_dir()
        if not grid:
            return {"base64": None}

        # Check pending sync data first (staging path)
        pending = self._pending_sync.get(rom_id, {})
        cover_path = pending.get("cover_path", "")

        # Fall back to registry
        if not cover_path:
            reg = self._state["shortcut_registry"].get(str(rom_id), {})
            cover_path = reg.get("cover_path", "")

        # Try staging filename as last resort
        if not cover_path:
            staging = os.path.join(grid, f"romm_{rom_id}_cover.png")
            if os.path.exists(staging):
                cover_path = staging

        if cover_path and os.path.exists(cover_path):
            try:
                with open(cover_path, "rb") as f:
                    return {"base64": base64.b64encode(f.read()).decode("ascii")}
            except Exception as e:
                decky.logger.warning(f"Failed to read artwork for rom {rom_id}: {e}")

        return {"base64": None}

    async def clear_sync_cache(self):
        """Clear last_sync timestamp to force a full re-fetch on next sync."""
        self._state["last_sync"] = None
        self._save_state()
        decky.logger.info("Sync cache cleared — next sync will do a full fetch")
        return {"success": True, "message": "Next sync will do a full fetch"}

    async def get_sync_stats(self):
        registry = self._state.get("shortcut_registry", {})
        platforms = set(e.get("platform_name", "") for e in registry.values())
        return {
            "last_sync": self._state.get("last_sync"),
            "platforms": len(platforms),
            "roms": len(registry),
            "total_shortcuts": len(registry),
        }

    async def get_rom_by_steam_app_id(self, app_id):
        app_id = int(app_id)
        for rom_id, entry in self._state["shortcut_registry"].items():
            if entry.get("app_id") == app_id:
                installed = self._state["installed_roms"].get(rom_id)
                return {
                    "rom_id": int(rom_id),
                    "name": entry.get("name", ""),
                    "platform_name": entry.get("platform_name", ""),
                    "platform_slug": entry.get("platform_slug", ""),
                    "installed": installed,
                }
        return None

    def _prune_orphaned_staging_artwork(self):
        """Remove orphaned romm_{rom_id}_cover.png staging files from Steam grid dir."""
        grid = self._grid_dir()
        if not grid or not os.path.isdir(grid):
            return
        registry = self._state.get("shortcut_registry", {})
        pruned = []
        for filename in os.listdir(grid):
            if not filename.startswith("romm_") or not filename.endswith("_cover.png"):
                continue
            # Extract rom_id from "romm_{rom_id}_cover.png"
            try:
                rom_id = filename[len("romm_"):-len("_cover.png")]
                int(rom_id)  # validate it's numeric
            except (ValueError, IndexError):
                continue
            should_remove = False
            if rom_id not in registry:
                # ROM no longer synced
                should_remove = True
            else:
                # Check if final artwork exists (staging is redundant leftover)
                app_id = registry[rom_id].get("app_id")
                if app_id:
                    final = os.path.join(grid, f"{app_id}p.png")
                    if os.path.exists(final):
                        should_remove = True
            if should_remove:
                try:
                    os.remove(os.path.join(grid, filename))
                    pruned.append(filename)
                except OSError as e:
                    decky.logger.warning(f"Failed to remove orphaned staging artwork {filename}: {e}")
        if pruned:
            decky.logger.info(f"Pruned {len(pruned)} orphaned staging artwork file(s)")
