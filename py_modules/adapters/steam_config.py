"""Adapter wrapping Steam VDF file access and shortcut ID generation.

Mostly stateless helpers — the only external dependency is the user's
Steam ``userdata`` directory (resolved from ``DECKY_USER_HOME``).
"""

from __future__ import annotations

import binascii
import logging
import os
import struct

import vdf


class SteamConfigAdapter:
    """Thin wrapper around Steam's on-disk config files."""

    def __init__(self, *, user_home: str, logger: logging.Logger) -> None:
        self._user_home = user_home
        self._logger = logger

    # -- Steam user directory -------------------------------------------------

    def find_steam_user_dir(self) -> str | None:
        """Find the active Steam user's userdata directory."""
        steam_paths = [
            os.path.join(self._user_home, ".local", "share", "Steam", "userdata"),
            os.path.join(self._user_home, ".steam", "steam", "userdata"),
        ]
        for base in steam_paths:
            if os.path.isdir(base):
                users = [d for d in os.listdir(base) if d.isdigit()]
                if len(users) == 1:
                    return os.path.join(base, users[0])
                if len(users) > 1:
                    users.sort(
                        key=lambda u, base=base: os.path.getmtime(os.path.join(base, u)),
                        reverse=True,
                    )
                    return os.path.join(base, users[0])
        return None

    def shortcuts_vdf_path(self) -> str | None:
        user_dir = self.find_steam_user_dir()
        if not user_dir:
            return None
        return os.path.join(user_dir, "config", "shortcuts.vdf")

    def grid_dir(self) -> str | None:
        user_dir = self.find_steam_user_dir()
        if not user_dir:
            return None
        grid = os.path.join(user_dir, "config", "grid")
        os.makedirs(grid, exist_ok=True)
        return grid

    # -- Shortcut ID generation -----------------------------------------------

    @staticmethod
    def generate_app_id(exe: str, appname: str) -> int:
        """Generate Steam shortcut app ID (signed int32). Deprecated."""
        key = exe + appname
        crc = binascii.crc32(key.encode("utf-8")) & 0xFFFFFFFF
        return struct.unpack("i", struct.pack("I", crc | 0x80000000))[0]

    @staticmethod
    def generate_artwork_id(exe: str, appname: str) -> int:
        """Generate unsigned artwork ID for grid filenames."""
        key = exe + appname
        crc = binascii.crc32(key.encode("utf-8")) & 0xFFFFFFFF
        return crc | 0x80000000

    # -- VDF read/write (deprecated — frontend uses SteamClient API) ----------

    def read_shortcuts(self) -> dict:
        path = self.shortcuts_vdf_path()
        if not path or not os.path.exists(path):
            return {"shortcuts": {}}
        with open(path, "rb") as f:
            return vdf.binary_loads(f.read())

    def write_shortcuts(self, data: dict) -> None:
        path = self.shortcuts_vdf_path()
        if not path:
            raise RuntimeError("Cannot find Steam shortcuts.vdf path")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(vdf.binary_dumps(data))
        os.replace(tmp_path, path)

    # -- Steam Input config ---------------------------------------------------

    def set_steam_input_config(self, app_ids: list, mode: str = "default") -> None:
        """Set UseSteamControllerConfig for given app_ids in localconfig.vdf.

        mode: "default" (remove key / "1"), "force_on" ("2"), "force_off" ("0")
        """
        user_dir = self.find_steam_user_dir()
        if not user_dir:
            self._logger.warning("Cannot find Steam user dir, skipping Steam Input config")
            return

        localconfig_path = os.path.join(user_dir, "config", "localconfig.vdf")
        if not os.path.exists(localconfig_path):
            self._logger.warning(f"localconfig.vdf not found at {localconfig_path}")
            return

        try:
            with open(localconfig_path, "r", encoding="utf-8") as f:
                data = vdf.load(f)
        except Exception as e:
            self._logger.error(f"Failed to parse localconfig.vdf: {e}")
            return

        # Navigate to the Apps section
        apps = data
        for key in ("UserLocalConfigStore", "Apps"):
            if key not in apps:
                if mode != "default":
                    apps[key] = {}
                else:
                    return  # Nothing to clean up
            apps = apps[key]

        value_map = {"force_on": "2", "force_off": "0"}
        changed = False
        for app_id in app_ids:
            app_key = str(app_id)
            if mode in value_map:
                if app_key not in apps:
                    apps[app_key] = {}
                apps[app_key]["UseSteamControllerConfig"] = value_map[mode]
                changed = True
            else:
                # Default: remove the override so Steam uses global settings
                if app_key in apps and "UseSteamControllerConfig" in apps[app_key]:
                    del apps[app_key]["UseSteamControllerConfig"]
                    if not apps[app_key]:
                        del apps[app_key]
                    changed = True

        if changed:
            try:
                tmp_path = localconfig_path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    vdf.dump(data, f, pretty=True)
                os.replace(tmp_path, localconfig_path)
                self._logger.info(f"Steam Input mode '{mode}' applied for {len(app_ids)} app(s)")
            except Exception as e:
                self._logger.error(f"Failed to write localconfig.vdf: {e}")

    # -- RetroArch input driver check -----------------------------------------

    def check_retroarch_input_driver(self) -> dict | None:
        """Check if RetroArch input_driver is set to a problematic value."""
        candidates = [
            "~/.var/app/net.retrodeck.retrodeck/config/retroarch/retroarch.cfg",
            "~/.var/app/org.libretro.RetroArch/config/retroarch/retroarch.cfg",
            "~/.config/retroarch/retroarch.cfg",
        ]
        for candidate in candidates:
            cfg_path = os.path.expanduser(candidate)
            try:
                with open(cfg_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("input_driver"):
                            parts = line.split("=", 1)
                            if len(parts) == 2:
                                val = parts[1].strip().strip('"').strip("'")
                                return {
                                    "warning": val == "x",
                                    "current": val,
                                    "config_path": cfg_path,
                                }
            except FileNotFoundError:
                continue
        return None

    def fix_retroarch_input_driver(self) -> dict:
        """Change RetroArch input_driver from 'x' to 'sdl2'."""
        check = self.check_retroarch_input_driver()
        if not check or not check.get("warning"):
            return {"success": False, "message": "No fix needed"}
        cfg_path = check["config_path"]
        try:
            with open(cfg_path, "r") as f:
                lines = f.readlines()
            with open(cfg_path, "w") as f:
                for line in lines:
                    if line.strip().startswith("input_driver"):
                        f.write('input_driver = "sdl2"\n')
                    else:
                        f.write(line)
            return {"success": True, "message": "Changed input_driver to sdl2"}
        except Exception as e:
            self._logger.error(f"Failed to fix RetroArch input_driver: {e}")
            return {"success": False, "message": "Operation failed"}
