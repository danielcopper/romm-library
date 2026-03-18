"""SteamGridService — SteamGridDB artwork management.

Handles SGDB API key verification, artwork fetching/caching, icon saving
to Steam grid directory, and orphaned artwork cache pruning.
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import ssl
import struct
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

from lib.certifi_bundle import ca_bundle as _ca_bundle

if TYPE_CHECKING:
    import asyncio
    import logging
    from collections.abc import Callable

    from services.protocols import RommApiProtocol, SteamConfigAdapter


_USER_AGENT = "decky-romm-sync/0.1"


class SteamGridService:
    """SteamGridDB artwork: API key management, artwork fetch/cache, icon save."""

    def __init__(
        self,
        *,
        romm_api: RommApiProtocol,
        steam_config: SteamConfigAdapter,
        state: dict,
        settings: dict,
        loop: asyncio.AbstractEventLoop,
        logger: logging.Logger,
        runtime_dir: str,
        save_state: Callable[[], None],
        save_settings_to_disk: Callable[[], None],
        pending_sync: dict,
    ) -> None:
        self._romm_api = romm_api
        self._steam_config = steam_config
        self._state = state
        self._settings = settings
        self._loop = loop
        self._logger = logger
        self._runtime_dir = runtime_dir
        self._save_state = save_state
        self._save_settings_to_disk = save_settings_to_disk
        self._pending_sync = pending_sync

    # -- logging -----------------------------------------------------------

    _LOG_LEVELS = {"debug": 0, "info": 1, "warn": 2, "error": 3}

    def _log_debug(self, msg: str) -> None:
        configured = self._settings.get("log_level", "warn")
        if self._LOG_LEVELS.get("debug", 0) >= self._LOG_LEVELS.get(configured, 2):
            self._logger.info(msg)

    # -- artwork dir -------------------------------------------------------

    def _sgdb_artwork_dir(self):
        art_dir = os.path.join(self._runtime_dir, "artwork")
        os.makedirs(art_dir, exist_ok=True)
        return art_dir

    # -- SGDB HTTP ---------------------------------------------------------

    def _sgdb_request(self, path):
        api_key = self._settings.get("steamgriddb_api_key", "")
        if not api_key:
            return None
        url = "https://www.steamgriddb.com/api/v2" + path
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("User-Agent", _USER_AGENT)
        # S4423: false positive — Python 3.10+ defaults are TLS 1.2+ secure
        ctx = ssl.create_default_context(cafile=_ca_bundle())
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            return json.loads(resp.read().decode())

    def _get_sgdb_game_id(self, igdb_id):
        try:
            result = self._sgdb_request(f"/games/igdb/{igdb_id}")
            if result and result.get("success") and result.get("data"):
                return result["data"]["id"]
        except Exception as e:
            self._logger.warning(f"SGDB lookup failed for IGDB {igdb_id}: {e}")
        return None

    # -- artwork download --------------------------------------------------

    def _download_sgdb_artwork(self, sgdb_game_id, rom_id, asset_type):
        type_map = {
            "hero": "heroes",
            "logo": "logos",
            "grid": "grids",
            "icon": "icons",
        }
        endpoint = type_map.get(asset_type)
        if not endpoint:
            return None

        art_dir = self._sgdb_artwork_dir()
        cached = os.path.join(art_dir, f"{rom_id}_{asset_type}.png")
        if os.path.exists(cached):
            return cached

        path = f"/{endpoint}/game/{sgdb_game_id}"
        if asset_type == "grid":
            path += "?dimensions=460x215,920x430"

        try:
            result = self._sgdb_request(path)
            if not result or not result.get("success") or not result.get("data"):
                return None
            image_url = result["data"][0]["url"]
            req = urllib.request.Request(image_url, method="GET")
            req.add_header("User-Agent", _USER_AGENT)
            # S4423: false positive — Python 3.10+ defaults are TLS 1.2+ secure
            ctx = ssl.create_default_context(cafile=_ca_bundle())
            tmp_path = cached + ".tmp"
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                with open(tmp_path, "wb") as f:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
            os.replace(tmp_path, cached)
            return cached
        except Exception as e:
            self._logger.warning(f"SGDB {asset_type} download failed for game {sgdb_game_id}: {e}")
            if os.path.exists(cached + ".tmp"):
                try:
                    os.remove(cached + ".tmp")
                except OSError:
                    pass
            return None

    # -- artwork base64 (callable) -----------------------------------------

    async def _read_file_as_base64(self, path):
        """Read a file and return base64-encoded string, or None on failure."""
        try:
            data = await self._loop.run_in_executor(None, lambda: pathlib.Path(path).read_bytes())
            return base64.b64encode(data).decode("ascii")
        except Exception as e:
            self._logger.warning(f"Failed to read file {path}: {e}")
            return None

    async def _resolve_sgdb_id(self, rom_id):
        """Resolve SGDB game ID from registry, pending sync, RomM API, or IGDB lookup."""
        rom_id_str = str(rom_id)
        reg = self._state["shortcut_registry"].get(rom_id_str, {})
        sgdb_id = reg.get("sgdb_id")
        igdb_id = reg.get("igdb_id")

        if not sgdb_id:
            pending = self._pending_sync.get(rom_id, {})
            sgdb_id = pending.get("sgdb_id")
            igdb_id = igdb_id or pending.get("igdb_id")

        # On-demand fetch from RomM API for pre-existing ROMs missing IDs
        if not sgdb_id:
            sgdb_id, igdb_id = await self._fetch_ids_from_romm(rom_id, igdb_id)

        # Fallback: look up SGDB via IGDB ID
        if not sgdb_id and igdb_id:
            sgdb_id = await self._loop.run_in_executor(None, self._get_sgdb_game_id, igdb_id)
            if sgdb_id and rom_id_str in self._state["shortcut_registry"]:
                self._state["shortcut_registry"][rom_id_str]["sgdb_id"] = sgdb_id
                self._save_state()

        return sgdb_id

    async def _fetch_ids_from_romm(self, rom_id, igdb_id):
        """Fetch sgdb_id and igdb_id from RomM API and update registry."""
        rom_id_str = str(rom_id)
        sgdb_id = None
        try:
            rom_data = await self._loop.run_in_executor(None, self._romm_api.get_rom, rom_id)
            if rom_data:
                sgdb_id = rom_data.get("sgdb_id")
                igdb_id = igdb_id or rom_data.get("igdb_id")
            self._log_debug(f"SGDB artwork: fetched sgdb_id={sgdb_id}, igdb_id={igdb_id} from RomM for rom_id={rom_id}")
            if rom_id_str in self._state["shortcut_registry"]:
                if sgdb_id:
                    self._state["shortcut_registry"][rom_id_str]["sgdb_id"] = sgdb_id
                if igdb_id:
                    self._state["shortcut_registry"][rom_id_str]["igdb_id"] = igdb_id
                self._save_state()
        except Exception as e:
            self._logger.warning(f"SGDB artwork: failed to fetch IDs from RomM for rom_id={rom_id}: {e}")
        return sgdb_id, igdb_id

    async def get_sgdb_artwork_base64(self, rom_id, asset_type_num):
        rom_id = int(rom_id)
        asset_type_num = int(asset_type_num)
        type_names = {1: "hero", 2: "logo", 3: "grid", 4: "icon"}
        asset_type = type_names.get(asset_type_num)
        self._log_debug(f"SGDB artwork request: rom_id={rom_id}, asset_type={asset_type_num}")
        if not asset_type:
            return {"base64": None, "no_api_key": False}

        art_dir = self._sgdb_artwork_dir()
        cached = os.path.join(art_dir, f"{rom_id}_{asset_type}.png")

        # Return from cache if available
        if os.path.exists(cached):
            self._log_debug(f"SGDB artwork cache hit: {cached}")
            b64 = await self._read_file_as_base64(cached)
            if b64:
                return {"base64": b64, "no_api_key": False}

        if not self._settings.get("steamgriddb_api_key"):
            self._log_debug("SGDB artwork skipped: no API key configured")
            return {"base64": None, "no_api_key": True}

        sgdb_id = await self._resolve_sgdb_id(rom_id)
        if not sgdb_id:
            self._log_debug(f"SGDB artwork skipped: no SGDB game found for rom_id={rom_id}")
            return {"base64": None, "no_api_key": False}

        path = await self._loop.run_in_executor(None, self._download_sgdb_artwork, sgdb_id, rom_id, asset_type)
        if path and os.path.exists(path):
            self._log_debug(f"SGDB artwork download success: rom_id={rom_id}, asset_type={asset_type}")
            b64 = await self._read_file_as_base64(path)
            if b64:
                return {"base64": b64, "no_api_key": False}
        else:
            self._log_debug(f"SGDB artwork download failed: rom_id={rom_id}, asset_type={asset_type}")

        return {"base64": None, "no_api_key": False}

    # -- API key management ------------------------------------------------

    def _verify_sgdb_api_key_io(self, api_key):
        """Sync helper for verify_sgdb_api_key — full HTTP round-trip in executor."""
        url = "https://www.steamgriddb.com/api/v2/search/autocomplete/test"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("User-Agent", _USER_AGENT)
        # S4423: false positive — Python 3.10+ defaults are TLS 1.2+ secure
        ctx = ssl.create_default_context(cafile=_ca_bundle())
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            return json.loads(resp.read().decode())

    async def verify_sgdb_api_key(self, api_key=None):
        # Use saved key if no valid key provided (modal pattern doesn't hold the real key)
        if not api_key or api_key == "••••":
            api_key = self._settings.get("steamgriddb_api_key", "")
        if not api_key:
            return {"success": False, "message": "No API key configured"}
        try:
            data = await self._loop.run_in_executor(None, self._verify_sgdb_api_key_io, api_key)
            if data.get("success"):
                return {"success": True, "message": "API key is valid"}
            return {"success": False, "message": "API key rejected by SteamGridDB"}
        except urllib.error.HTTPError as e:
            self._logger.warning(f"SGDB API key verification HTTP error: {e.code}")
            if e.code in (401, 403):
                return {"success": False, "message": "Invalid API key"}
            return {"success": False, "message": f"SteamGridDB error: HTTP {e.code}"}
        except Exception as e:
            self._logger.error(f"SGDB API key verification failed: {e}")
            return {"success": False, "message": f"Connection failed: {e}"}

    def save_sgdb_api_key(self, api_key):
        if api_key and api_key != "••••":
            self._settings["steamgriddb_api_key"] = api_key
            self._save_settings_to_disk()
        return {"success": True, "message": "SteamGridDB API key saved"}

    # -- cache pruning -----------------------------------------------------

    def prune_orphaned_artwork_cache(self):
        """Remove SGDB artwork cache files for rom_ids not in the shortcut registry."""
        art_dir = os.path.join(self._runtime_dir, "artwork")
        if not os.path.isdir(art_dir):
            return
        registry = self._state.get("shortcut_registry", {})
        pruned = 0
        for filename in os.listdir(art_dir):
            # Always remove leftover .tmp files
            if filename.endswith(".tmp"):
                try:
                    os.remove(os.path.join(art_dir, filename))
                    pruned += 1
                    self._logger.info(f"Removed leftover artwork tmp: {filename}")
                except OSError as e:
                    self._logger.warning(f"Failed to remove artwork tmp {filename}: {e}")
                continue
            # Expected format: {rom_id}_{type}.png
            parts = filename.split("_", 1)
            if not parts:
                continue
            rom_id = parts[0]
            if rom_id not in registry:
                try:
                    os.remove(os.path.join(art_dir, filename))
                    pruned += 1
                except OSError as e:
                    self._logger.warning(f"Failed to remove orphaned artwork {filename}: {e}")
        if pruned:
            self._logger.info(f"Pruned {pruned} orphaned SGDB artwork cache file(s)")

    # -- icon saving -------------------------------------------------------

    def _save_icon_to_grid(self, app_id, icon_bytes):
        """Write icon PNG to Steam's grid dir and update shortcuts.vdf icon field."""
        grid_dir = self._steam_config.grid_dir()
        if not grid_dir:
            self._logger.warning("Cannot find Steam grid directory for icon save")
            return False

        # Write icon file to grid dir
        icon_path = os.path.join(grid_dir, f"{app_id}_icon.png")
        tmp_path = icon_path + ".tmp"
        try:
            with open(tmp_path, "wb") as f:
                f.write(icon_bytes)
            os.replace(tmp_path, icon_path)
        except Exception as e:
            self._logger.error(f"Failed to write icon file {icon_path}: {e}")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            return False

        # Update shortcuts.vdf icon field
        try:
            vdf_data = self._steam_config.read_shortcuts()
            # Convert unsigned app_id to signed int32 for VDF comparison
            signed_id = struct.unpack("i", struct.pack("I", app_id & 0xFFFFFFFF))[0]
            shortcuts = vdf_data.get("shortcuts", {})
            for entry in shortcuts.values():
                if entry.get("appid") == signed_id:
                    entry["icon"] = icon_path
                    break
            self._steam_config.write_shortcuts(vdf_data)
        except Exception as e:
            self._logger.warning(f"Failed to update shortcuts.vdf icon field: {e}")
            # Icon file is still saved, just VDF field not set — non-fatal

        return True

    async def save_shortcut_icon(self, app_id, icon_base64):
        """Save icon PNG to Steam grid dir and update VDF. Called from frontend."""
        app_id = int(app_id)
        try:
            icon_bytes = base64.b64decode(icon_base64)
        except Exception as e:
            self._logger.error(f"Failed to decode icon base64: {e}")
            return {"success": False}

        success = await self._loop.run_in_executor(None, self._save_icon_to_grid, app_id, icon_bytes)
        return {"success": success}
