"""StateMixin — thin delegation shim to PersistenceAdapter for I/O.

File read/write logic lives in ``adapters.persistence.PersistenceAdapter``.
This mixin keeps business logic (migrations, pruning, logging) and delegates
pure I/O through a lazy ``_persistence`` property.
"""

import os
from typing import TYPE_CHECKING

import decky
from adapters.persistence import PersistenceAdapter

if TYPE_CHECKING:
    from typing import Protocol

    class _StateDeps(Protocol):
        settings: dict
        _state: dict
        _metadata_cache: dict
        _achievements_cache: dict


class StateMixin(_StateDeps if TYPE_CHECKING else object):
    # -- lazy property: auto-creates adapter on first access ---------------

    @property
    def _persistence(self) -> PersistenceAdapter:
        if not hasattr(self, "_StateMixin__persistence"):
            self._StateMixin__persistence = PersistenceAdapter(
                decky.DECKY_PLUGIN_SETTINGS_DIR,
                decky.DECKY_PLUGIN_RUNTIME_DIR,
                decky.logger,
            )
        return self._StateMixin__persistence

    @_persistence.setter
    def _persistence(self, value: PersistenceAdapter) -> None:
        self._StateMixin__persistence = value

    # -- settings ----------------------------------------------------------

    def _load_settings(self):
        self.settings = self._persistence.load_settings()
        # Migrate old boolean setting
        if "disable_steam_input" in self.settings:
            if self.settings.pop("disable_steam_input"):
                self.settings["steam_input_mode"] = "force_off"
            self._save_settings_to_disk()
        # Migrate old boolean debug_logging to log_level
        if "debug_logging" in self.settings:
            if self.settings.pop("debug_logging"):
                self.settings.setdefault("log_level", "debug")
            self._save_settings_to_disk()
        self.settings.setdefault("log_level", "warn")

    def _save_settings_to_disk(self):
        self._persistence.save_settings(self.settings)

    # -- logging -----------------------------------------------------------

    LOG_LEVELS = {"debug": 0, "info": 1, "warn": 2, "error": 3}

    def _log_debug(self, msg):
        """Log a message only when log_level allows debug messages."""
        configured = self.settings.get("log_level", "warn")
        if self.LOG_LEVELS.get("debug", 0) >= self.LOG_LEVELS.get(configured, 2):
            decky.logger.info(msg)

    # -- state -------------------------------------------------------------

    def _load_state(self):
        self._state = self._persistence.load_state(self._state)

    def _save_state(self):
        self._persistence.save_state(self._state)

    def _prune_stale_installed_roms(self):
        """Remove installed_roms entries whose files no longer exist on disk."""
        pruned = []
        for rom_id, entry in list(self._state["installed_roms"].items()):
            file_path = entry.get("file_path", "")
            rom_dir = entry.get("rom_dir", "")
            if (file_path and os.path.exists(file_path)) or (rom_dir and os.path.exists(rom_dir)):
                continue
            decky.logger.info(f"Pruned stale installed_roms entry: {rom_id} ({file_path})")
            pruned.append(rom_id)
        for rom_id in pruned:
            del self._state["installed_roms"][rom_id]
        if pruned:
            self._save_state()

    def _prune_stale_registry(self):
        """Remove shortcut_registry entries with missing or invalid app_id."""
        pruned = []
        for rom_id, entry in list(self._state["shortcut_registry"].items()):
            app_id = entry.get("app_id")
            if not app_id or not isinstance(app_id, int):
                decky.logger.info(f"Pruned stale registry entry: rom_id={rom_id} (invalid app_id={app_id})")
                pruned.append(rom_id)
        for rom_id in pruned:
            del self._state["shortcut_registry"][rom_id]
        if pruned:
            self._save_state()

    # -- metadata cache ----------------------------------------------------

    def _load_metadata_cache(self):
        self._metadata_cache = self._persistence.load_metadata_cache()

    def _save_metadata_cache(self):
        self._persistence.save_metadata_cache(self._metadata_cache)
