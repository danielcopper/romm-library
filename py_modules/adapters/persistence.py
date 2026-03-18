"""Persistence adapter — pure I/O for settings, state, and metadata cache files.

No business logic, no migration logic, no ``import decky``.
"""

import fcntl
import json
import logging
import os

_STATE_VERSION = 1
_METADATA_CACHE_VERSION = 1

DEFAULT_SETTINGS: dict = {
    "romm_url": "",
    "romm_user": "",
    "romm_pass": "",
    "enabled_platforms": {},
    "steam_input_mode": "default",
    "steamgriddb_api_key": "",
    "romm_allow_insecure_ssl": False,
    # NOTE: log_level default is NOT here — it's applied in Plugin._load_settings()
    # AFTER the debug_logging → log_level migration runs.
}


class PersistenceAdapter:
    """Thin I/O layer for JSON persistence files used by the plugin.

    Parameters
    ----------
    settings_dir:
        Absolute path to the directory that holds ``settings.json``
        (typically ``decky.DECKY_PLUGIN_SETTINGS_DIR``).
    runtime_dir:
        Absolute path to the directory that holds ``state.json`` and
        ``metadata_cache.json`` (typically ``decky.DECKY_PLUGIN_RUNTIME_DIR``).
    logger:
        A standard-library ``logging.Logger`` instance.
    """

    def __init__(self, settings_dir: str, runtime_dir: str, logger: logging.Logger) -> None:
        self._settings_dir = settings_dir
        self._runtime_dir = runtime_dir
        self._logger = logger

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def load_settings(self) -> dict:
        """Read ``settings.json``, apply defaults, and fix permissions.

        Migration logic (e.g. renaming old keys) is intentionally NOT
        included here — that belongs in ``Plugin._load_settings()``.
        """
        settings_path = os.path.join(self._settings_dir, "settings.json")
        try:
            with open(settings_path, "r") as f:
                settings = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            settings = {}

        for key, default in DEFAULT_SETTINGS.items():
            settings.setdefault(key, default)

        # Enforce 0600 on settings file (migrate from world-readable 0644)
        if os.path.exists(settings_path):
            current_mode = os.stat(settings_path).st_mode & 0o777
            if current_mode != 0o600:
                os.chmod(settings_path, 0o600)

        return settings

    def save_settings(self, data: dict) -> None:
        """Atomic write of *data* to ``settings.json`` with 0600 permissions."""
        os.makedirs(self._settings_dir, exist_ok=True)
        settings_path = os.path.join(self._settings_dir, "settings.json")
        tmp_path = settings_path + ".tmp"
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, settings_path)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def load_state(self, defaults: dict) -> dict:
        """Read ``state.json`` and merge with *defaults*.

        Returns the merged dict.  If the file is missing or corrupt the
        returned dict is a copy of *defaults* with the version stamp.
        """
        state_path = os.path.join(self._runtime_dir, "state.json")
        state = dict(defaults)
        try:
            with open(state_path, "r") as f:
                saved = json.load(f)
            if not isinstance(saved, dict):
                saved = {}
            if "version" not in saved:
                saved["version"] = _STATE_VERSION
            state.update(saved)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        state.setdefault("version", _STATE_VERSION)
        return state

    def save_state(self, data: dict) -> None:
        """Atomic write of *data* to ``state.json`` with flock."""
        os.makedirs(self._runtime_dir, exist_ok=True)
        state_path = os.path.join(self._runtime_dir, "state.json")
        tmp_path = state_path + ".tmp"
        lock_fd = os.open(state_path + ".lock", os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, state_path)
        finally:
            os.close(lock_fd)

    # ------------------------------------------------------------------
    # Metadata cache
    # ------------------------------------------------------------------

    def load_metadata_cache(self) -> dict:
        """Read ``metadata_cache.json`` with version check."""
        cache_path = os.path.join(self._runtime_dir, "metadata_cache.json")
        try:
            with open(cache_path, "r") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                loaded = {}
            if "version" not in loaded:
                loaded["version"] = _METADATA_CACHE_VERSION
            return loaded
        except (FileNotFoundError, json.JSONDecodeError):
            return {"version": _METADATA_CACHE_VERSION}

    def save_metadata_cache(self, data: dict) -> None:
        """Atomic write of *data* to ``metadata_cache.json`` with flock."""
        os.makedirs(self._runtime_dir, exist_ok=True)
        cache_path = os.path.join(self._runtime_dir, "metadata_cache.json")
        tmp_path = cache_path + ".tmp"
        lock_fd = os.open(cache_path + ".lock", os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, cache_path)
        finally:
            os.close(lock_fd)

    # ------------------------------------------------------------------
    # Firmware cache
    # ------------------------------------------------------------------

    def load_firmware_cache(self) -> dict:
        """Read ``firmware_cache.json``."""
        cache_path = os.path.join(self._runtime_dir, "firmware_cache.json")
        try:
            with open(cache_path, "r") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                return {}
            return loaded
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_firmware_cache(self, data: dict) -> None:
        """Atomic write of *data* to ``firmware_cache.json`` with flock."""
        os.makedirs(self._runtime_dir, exist_ok=True)
        cache_path = os.path.join(self._runtime_dir, "firmware_cache.json")
        tmp_path = cache_path + ".tmp"
        lock_fd = os.open(cache_path + ".lock", os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, cache_path)
        finally:
            os.close(lock_fd)
