import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from adapters.romm.client import RommHttpClient
from adapters.steam_config import SteamConfigAdapter
from fakes.fake_save_api import FakeSaveApi
from services.playtime import PlaytimeService
from services.save_sync import SaveSyncService
from services.sync import SyncService

# conftest.py patches decky before this import
from main import Plugin


def _no_retry(fn, *a, **kw):
    return fn(*a, **kw)


@pytest.fixture
def plugin(tmp_path):
    p = Plugin()
    p.settings = {
        "romm_url": "http://romm.local",
        "romm_user": "user",
        "romm_pass": "pass",
        "enabled_platforms": {},
        "log_level": "warn",
    }
    p._http_client = RommHttpClient(p.settings, __import__("decky").DECKY_PLUGIN_DIR, logging.getLogger("test"))
    p._state = {
        "shortcut_registry": {},
        "installed_roms": {},
        "last_sync": None,
        "sync_stats": {},
    }
    p._metadata_cache = {}

    import decky

    decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

    steam_config = SteamConfigAdapter(user_home=decky.DECKY_USER_HOME, logger=decky.logger)
    p._steam_config = steam_config

    p._sync_service = SyncService(
        http_client=p._http_client,
        steam_config=steam_config,
        state=p._state,
        settings=p.settings,
        metadata_cache=p._metadata_cache,
        loop=asyncio.get_event_loop(),
        logger=decky.logger,
        plugin_dir=decky.DECKY_PLUGIN_DIR,
        emit=decky.emit,
        plugin=p,
    )
    decky.DECKY_USER_HOME = str(tmp_path)

    # Wire services with FakeSaveApi
    fake_api = FakeSaveApi()
    p._save_sync_state = SaveSyncService.make_default_state()
    saves_path = str(tmp_path / "retrodeck" / "saves")

    p._save_sync_service = SaveSyncService(
        save_api=fake_api,
        with_retry=_no_retry,
        is_retryable=lambda e: isinstance(e, ConnectionError),
        state=p._state,
        save_sync_state=p._save_sync_state,
        loop=asyncio.get_event_loop(),
        logger=logging.getLogger("test"),
        runtime_dir=str(tmp_path),
        get_saves_path=lambda: saves_path,
    )
    p._save_sync_service.init_state()

    p._playtime_service = PlaytimeService(
        save_api=fake_api,
        with_retry=_no_retry,
        is_retryable=lambda e: isinstance(e, ConnectionError),
        save_sync_state=p._save_sync_state,
        loop=asyncio.get_event_loop(),
        logger=logging.getLogger("test"),
        save_state=p._save_sync_service.save_state,
    )

    # Store fake_api on plugin for test access
    p._fake_api = fake_api

    # Enable save sync for tests — matches pre-feature-flag behavior
    p._save_sync_state["settings"]["save_sync_enabled"] = True
    return p


@pytest.fixture(autouse=True)
async def _set_event_loop(plugin):
    """Ensure plugin and service loops match the running event loop for async tests."""
    loop = asyncio.get_event_loop()
    plugin.loop = loop
    plugin._save_sync_service._loop = loop
    plugin._playtime_service._loop = loop


def _install_rom(plugin, tmp_path, rom_id=42, system="gba", file_name="pokemon.gba"):
    """Helper: register a ROM in installed_roms state."""
    plugin._state["installed_roms"][str(rom_id)] = {
        "rom_id": rom_id,
        "file_name": file_name,
        "file_path": str(tmp_path / "retrodeck" / "roms" / system / file_name),
        "system": system,
        "platform_slug": system,
        "installed_at": "2026-01-01T00:00:00",
    }


def _create_save(tmp_path, system="gba", rom_name="pokemon", content=b"\x00" * 1024, ext=".srm"):
    """Helper: create a save file on disk."""
    saves_dir = tmp_path / "retrodeck" / "saves" / system
    saves_dir.mkdir(parents=True, exist_ok=True)
    save_file = saves_dir / (rom_name + ext)
    save_file.write_bytes(content)
    return save_file


def _server_save(
    save_id=100, rom_id=42, filename="pokemon.srm", updated_at="2026-02-17T06:00:00Z", file_size_bytes=1024
):
    """Helper: build a server save response dict (matches RomM 4.6.1 SaveSchema)."""
    return {
        "id": save_id,
        "rom_id": rom_id,
        "file_name": filename,
        "updated_at": updated_at,
        "file_size_bytes": file_size_bytes,
        "emulator": "retroarch",
        "download_path": f"/saves/{filename}",
    }


# ============================================================================
# Device Registration (Plugin callable integration)
# ============================================================================


class TestDeviceRegistration:
    """Tests for ensure_device_registered (local UUID generation)."""

    @pytest.mark.asyncio
    async def test_generates_local_uuid(self, plugin, tmp_path):
        """First call generates a local UUID, no server call needed."""
        result = await plugin.ensure_device_registered()

        assert result["success"] is True
        assert result["device_id"]
        assert len(result["device_id"]) == 36  # UUID format
        assert plugin._save_sync_state["device_id"] == result["device_id"]

        # Persisted to disk
        path = tmp_path / "save_sync_state.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["device_id"] == result["device_id"]

    @pytest.mark.asyncio
    async def test_already_registered_returns_cached(self, plugin):
        """If device_id already set, returns immediately without generating new one."""
        plugin._save_sync_state["device_id"] = "existing-uuid"
        plugin._save_sync_state["device_name"] = "myhost"

        result = await plugin.ensure_device_registered()

        assert result["success"] is True
        assert result["device_id"] == "existing-uuid"
        assert result["device_name"] == "myhost"

    @pytest.mark.asyncio
    async def test_sets_hostname_as_device_name(self, plugin):
        """Device name is set to the local hostname."""
        with patch("socket.gethostname", return_value="steamdeck"):
            result = await plugin.ensure_device_registered()

        assert result["device_name"] == "steamdeck"
        assert plugin._save_sync_state["device_name"] == "steamdeck"

    @pytest.mark.asyncio
    async def test_generates_unique_ids(self, plugin):
        """Each new registration generates a unique UUID."""
        result1 = await plugin.ensure_device_registered()
        id1 = result1["device_id"]

        # Reset state to force new generation
        plugin._save_sync_state["device_id"] = None
        result2 = await plugin.ensure_device_registered()
        id2 = result2["device_id"]

        assert id1 != id2


# ============================================================================
# Pre-Launch Sync (Plugin callable integration)
# ============================================================================


class TestPreLaunchSync:
    """Tests for pre_launch_sync callable."""

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self, plugin):
        """Returns early when sync_before_launch is false."""
        plugin._save_sync_state["settings"]["sync_before_launch"] = False

        result = await plugin.pre_launch_sync(42)

        assert result["synced"] == 0
        assert "disabled" in result["message"].lower()


# ============================================================================
# Post-Exit Sync (Plugin callable integration)
# ============================================================================


class TestPostExitSync:
    """Tests for post_exit_sync callable."""

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self, plugin):
        """Returns early when sync_after_exit is false."""
        plugin._save_sync_state["settings"]["sync_after_exit"] = False

        result = await plugin.post_exit_sync(42)

        assert result["synced"] == 0
        assert "disabled" in result["message"].lower()


# ============================================================================
# Playtime Tracking (Plugin callable integration)
# ============================================================================


class TestPlaytimeTracking:
    """Tests for session playtime recording."""

    @pytest.mark.asyncio
    async def test_session_start_records_timestamp(self, plugin):
        """record_session_start saves start time in playtime dict."""
        result = await plugin.record_session_start(42)

        assert result["success"] is True
        entry = plugin._save_sync_state["playtime"]["42"]
        assert entry["last_session_start"] is not None
        # Should be a valid ISO datetime
        datetime.fromisoformat(entry["last_session_start"])

    @pytest.mark.asyncio
    async def test_session_end_calculates_delta(self, plugin):
        """record_session_end computes correct duration."""
        plugin._save_sync_state.setdefault("playtime", {})
        start_time = datetime.now(timezone.utc) - timedelta(seconds=600)
        plugin._save_sync_state["playtime"]["42"] = {
            "total_seconds": 0,
            "session_count": 0,
            "last_session_start": start_time.isoformat(),
            "last_session_duration_sec": None,
            "offline_deltas": [],
        }

        result = await plugin.record_session_end(42)

        assert result["success"] is True
        assert result["duration_sec"] >= 590  # ~600s minus execution time
        assert result["total_seconds"] >= 590

    @pytest.mark.asyncio
    async def test_delta_accumulated(self, plugin):
        """Playtime delta added to existing total."""
        start_time = datetime.now(timezone.utc) - timedelta(seconds=300)
        plugin._save_sync_state["playtime"] = {
            "42": {
                "total_seconds": 1000,
                "session_count": 5,
                "last_session_start": start_time.isoformat(),
                "last_session_duration_sec": None,
                "offline_deltas": [],
            }
        }

        await plugin.record_session_end(42)

        total = plugin._save_sync_state["playtime"]["42"]["total_seconds"]
        assert total >= 1290  # 1000 + ~300

    @pytest.mark.asyncio
    async def test_session_count_incremented(self, plugin):
        """Session count goes up on end."""
        start_time = datetime.now(timezone.utc) - timedelta(seconds=10)
        plugin._save_sync_state["playtime"] = {
            "42": {
                "total_seconds": 0,
                "session_count": 5,
                "last_session_start": start_time.isoformat(),
                "last_session_duration_sec": None,
                "offline_deltas": [],
            }
        }

        result = await plugin.record_session_end(42)

        assert result["session_count"] == 6

    @pytest.mark.asyncio
    async def test_end_without_start(self, plugin):
        """record_session_end without active session returns failure."""
        result = await plugin.record_session_end(42)

        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_session_start_clears_on_end(self, plugin):
        """last_session_start is cleared after session end."""
        start_time = datetime.now(timezone.utc) - timedelta(seconds=10)
        plugin._save_sync_state["playtime"] = {
            "42": {
                "total_seconds": 0,
                "session_count": 0,
                "last_session_start": start_time.isoformat(),
                "last_session_duration_sec": None,
                "offline_deltas": [],
            }
        }

        await plugin.record_session_end(42)

        assert plugin._save_sync_state["playtime"]["42"]["last_session_start"] is None

    @pytest.mark.asyncio
    async def test_duration_clamped_to_24h(self, plugin):
        """Duration clamped to max 24 hours."""
        start_time = datetime.now(timezone.utc) - timedelta(hours=48)
        plugin._save_sync_state["playtime"] = {
            "42": {
                "total_seconds": 0,
                "session_count": 0,
                "last_session_start": start_time.isoformat(),
                "last_session_duration_sec": None,
                "offline_deltas": [],
            }
        }

        result = await plugin.record_session_end(42)

        assert result["duration_sec"] <= 86400  # 24h max


# ============================================================================
# Get All Playtime (Plugin callable integration)
# ============================================================================


class TestGetAllPlaytime:
    """Tests for get_all_playtime callable."""

    @pytest.mark.asyncio
    async def test_returns_all_playtime_entries(self, plugin):
        """Returns all playtime entries from state."""
        plugin._save_sync_state["playtime"] = {
            "42": {"total_seconds": 3000, "session_count": 5},
            "99": {"total_seconds": 600, "session_count": 1},
        }
        result = await plugin.get_all_playtime()
        assert result["playtime"]["42"]["total_seconds"] == 3000
        assert result["playtime"]["99"]["total_seconds"] == 600

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_playtime(self, plugin):
        """Returns empty dict when no playtime data exists."""
        plugin._save_sync_state["playtime"] = {}
        result = await plugin.get_all_playtime()
        assert result["playtime"] == {}


# ============================================================================
# Save Sync Settings (Plugin callable integration)
# ============================================================================


class TestSaveSyncSettings:
    """Tests for get/update save sync settings."""

    @pytest.mark.asyncio
    async def test_get_returns_current(self, plugin):
        """Returns current settings."""
        result = await plugin.get_save_sync_settings()

        assert result["conflict_mode"] == "ask_me"
        assert result["sync_before_launch"] is True
        assert result["sync_after_exit"] is True
        assert result["clock_skew_tolerance_sec"] == 60

    @pytest.mark.asyncio
    async def test_update_changes_settings(self, plugin, tmp_path):
        """Updates and persists settings."""
        result = await plugin.update_save_sync_settings(
            {
                "conflict_mode": "always_download",
                "sync_before_launch": False,
            }
        )

        assert result["success"] is True
        assert result["settings"]["conflict_mode"] == "always_download"
        assert result["settings"]["sync_before_launch"] is False
        # sync_after_exit unchanged
        assert result["settings"]["sync_after_exit"] is True

        # Persisted
        path = tmp_path / "save_sync_state.json"
        data = json.loads(path.read_text())
        assert data["settings"]["conflict_mode"] == "always_download"

    @pytest.mark.asyncio
    async def test_invalid_conflict_mode_ignored(self, plugin):
        """Unknown conflict mode is silently ignored."""
        result = await plugin.update_save_sync_settings(
            {
                "conflict_mode": "invalid_mode",
            }
        )

        assert result["success"] is True
        # Original value preserved
        assert result["settings"]["conflict_mode"] == "ask_me"

    @pytest.mark.asyncio
    async def test_unknown_keys_ignored(self, plugin):
        """Unknown settings keys are silently ignored."""
        result = await plugin.update_save_sync_settings(
            {
                "unknown_key": "value",
                "conflict_mode": "ask_me",
            }
        )

        assert result["success"] is True
        assert result["settings"]["conflict_mode"] == "ask_me"
        assert "unknown_key" not in result["settings"]

    @pytest.mark.asyncio
    async def test_clock_skew_clamped_to_zero(self, plugin):
        """Negative clock_skew_tolerance_sec clamped to 0."""
        result = await plugin.update_save_sync_settings(
            {
                "clock_skew_tolerance_sec": -10,
            }
        )

        assert result["settings"]["clock_skew_tolerance_sec"] == 0

    @pytest.mark.asyncio
    async def test_boolean_coercion(self, plugin):
        """sync toggles coerced to bool."""
        result = await plugin.update_save_sync_settings(
            {
                "sync_before_launch": 0,
                "sync_after_exit": 1,
            }
        )

        assert result["settings"]["sync_before_launch"] is False
        assert result["settings"]["sync_after_exit"] is True


# ============================================================================
# Manual Sync All (Plugin callable integration)
# ============================================================================


class TestSyncAllSaves:
    """Tests for sync_all_saves."""

    @pytest.mark.asyncio
    async def test_no_installed_roms(self, plugin):
        """Empty installed_roms completes gracefully."""
        plugin._save_sync_state["device_id"] = "dev-1"

        result = await plugin.sync_all_saves()

        assert result["success"] is True
        assert result["roms_checked"] == 0
        assert result["synced"] == 0


# ============================================================================
# Single ROM Sync (Plugin callable integration)
# ============================================================================


class TestSyncRomSaves:
    """Tests for sync_rom_saves callable (bidirectional per-ROM sync)."""

    @pytest.mark.asyncio
    async def test_rom_not_installed(self, plugin):
        """Non-installed ROM returns 0 synced."""
        plugin._save_sync_state["device_id"] = "dev-1"

        result = await plugin.sync_rom_saves(999)

        assert result["success"] is True
        assert result["synced"] == 0


# ============================================================================
# Pending Conflicts (Plugin callable integration)
# ============================================================================


class TestPendingConflicts:
    """Tests for conflict queue management."""

    @pytest.mark.asyncio
    async def test_get_pending_conflicts_deprecated_stub(self, plugin):
        """Deprecated stub always returns empty list."""
        result = await plugin.get_pending_conflicts()

        assert result["conflicts"] == []

    @pytest.mark.asyncio
    async def test_get_empty_conflicts(self, plugin):
        """Returns empty list (deprecated stub)."""
        result = await plugin.get_pending_conflicts()

        assert result["conflicts"] == []

    @pytest.mark.asyncio
    async def test_resolve_invalid_resolution(self, plugin):
        """Invalid resolution string is rejected."""
        result = await plugin.resolve_conflict(42, "pokemon.srm", "invalid")

        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_resolve_missing_server_save_id(self, plugin):
        """Resolving without server_save_id returns failure."""
        result = await plugin.resolve_conflict(42, "pokemon.srm", "upload")

        assert result["success"] is False


# ============================================================================
# Retry Logic (MRO verification)
# ============================================================================


class TestRetryMRO:
    """Verify with_retry is accessible on Plugin via _http_client."""

    def test_with_retry_accessible_via_http_client(self, plugin):
        """with_retry should be accessible via _http_client."""
        fn = MagicMock(return_value="ok")
        result = plugin._http_client.with_retry(fn, "arg1")
        assert result == "ok"
        fn.assert_called_once_with("arg1")


# ============================================================================
# Conflict Resolution Edge Cases (Plugin callable integration)
# ============================================================================


class TestResolveConflictEdgeCases:
    """Edge cases for resolve_conflict callable — tests that work without mixin methods."""

    @pytest.mark.asyncio
    async def test_resolve_upload_without_server_save_id(self, plugin, tmp_path):
        """Resolving upload without server_save_id returns error."""
        _install_rom(plugin, tmp_path)
        save_file = _create_save(tmp_path)

        plugin._save_sync_state["device_id"] = "dev-1"

        result = await plugin.resolve_conflict(
            42,
            "pokemon.srm",
            "upload",
            server_save_id=None,
            local_path=str(save_file),
        )

        assert result["success"] is False
        assert "server_save_id" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_resolve_download_missing_server_save_id(self, plugin, tmp_path):
        """Resolving download when server_save_id is missing fails gracefully."""
        _install_rom(plugin, tmp_path)

        result = await plugin.resolve_conflict(
            42,
            "pokemon.srm",
            "download",
            server_save_id=None,
            local_path=str(tmp_path / "retrodeck" / "saves" / "gba" / "pokemon.srm"),
        )

        assert result["success"] is False
        assert "server_save_id" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_resolve_upload_local_file_deleted(self, plugin, tmp_path):
        """Resolving upload when local file was deleted fails gracefully."""
        _install_rom(plugin, tmp_path)
        # Note: no save file created on disk

        result = await plugin.resolve_conflict(
            42,
            "pokemon.srm",
            "upload",
            server_save_id=100,
            local_path=str(tmp_path / "retrodeck" / "saves" / "gba" / "pokemon.srm"),
        )

        assert result["success"] is False
        assert "not found" in result["message"].lower()


# ============================================================================
# Feature Flag: save_sync_enabled (Plugin callable integration)
# ============================================================================


class TestSaveSyncFeatureFlag:
    """Tests for the save_sync_enabled feature flag (off by default)."""

    @pytest.mark.asyncio
    async def test_default_disabled(self, plugin):
        """save_sync_enabled defaults to False in fresh state."""
        plugin._save_sync_state.update(
            SaveSyncService.make_default_state()
        )  # Reset to defaults (no test fixture override)
        settings = plugin._save_sync_state["settings"]
        assert settings["save_sync_enabled"] is False

    @pytest.mark.asyncio
    async def test_ensure_device_disabled(self, plugin):
        """ensure_device_registered returns disabled marker when save sync off."""
        plugin._save_sync_state["settings"]["save_sync_enabled"] = False
        result = await plugin.ensure_device_registered()
        assert result["success"] is False
        assert result.get("disabled") is True
        assert plugin._save_sync_state["device_id"] is None

    @pytest.mark.asyncio
    async def test_pre_launch_sync_disabled(self, plugin):
        """pre_launch_sync skips when save sync disabled."""
        plugin._save_sync_state["settings"]["save_sync_enabled"] = False
        result = await plugin.pre_launch_sync(42)
        assert result["success"] is True
        assert result["synced"] == 0
        assert "disabled" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_post_exit_sync_disabled(self, plugin):
        """post_exit_sync skips when save sync disabled."""
        plugin._save_sync_state["settings"]["save_sync_enabled"] = False
        result = await plugin.post_exit_sync(42)
        assert result["success"] is True
        assert result["synced"] == 0
        assert "disabled" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_sync_rom_saves_disabled(self, plugin):
        """sync_rom_saves returns error when save sync disabled."""
        plugin._save_sync_state["settings"]["save_sync_enabled"] = False
        result = await plugin.sync_rom_saves(42)
        assert result["success"] is False
        assert "disabled" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_sync_all_saves_disabled(self, plugin):
        """sync_all_saves returns error when save sync disabled."""
        plugin._save_sync_state["settings"]["save_sync_enabled"] = False
        result = await plugin.sync_all_saves()
        assert result["success"] is False
        assert "disabled" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_enable_via_settings_update(self, plugin):
        """save_sync_enabled can be toggled via update_save_sync_settings."""
        plugin._save_sync_state["settings"]["save_sync_enabled"] = False
        result = await plugin.update_save_sync_settings({"save_sync_enabled": True})
        assert result["success"] is True
        assert plugin._save_sync_state["settings"]["save_sync_enabled"] is True

    @pytest.mark.asyncio
    async def test_disable_via_settings_update(self, plugin):
        """save_sync_enabled can be disabled via update_save_sync_settings."""
        result = await plugin.update_save_sync_settings({"save_sync_enabled": False})
        assert result["success"] is True
        assert plugin._save_sync_state["settings"]["save_sync_enabled"] is False

    @pytest.mark.asyncio
    async def test_get_settings_includes_flag(self, plugin):
        """get_save_sync_settings returns save_sync_enabled field."""
        result = await plugin.get_save_sync_settings()
        assert "save_sync_enabled" in result

    @pytest.mark.asyncio
    async def test_is_save_sync_enabled_helper(self, plugin):
        """_is_save_sync_enabled reflects the settings value."""
        plugin._save_sync_state["settings"]["save_sync_enabled"] = True
        assert plugin._save_sync_service._is_save_sync_enabled() is True
        plugin._save_sync_state["settings"]["save_sync_enabled"] = False
        assert plugin._save_sync_service._is_save_sync_enabled() is False


# ============================================================================
# Delete Local Saves (Plugin callable integration)
# ============================================================================


@pytest.mark.asyncio
async def test_delete_local_saves_happy_path(plugin, tmp_path):
    """Deleting local saves removes files and cleans sync state."""
    rom_id = 100
    system = "snes"
    rom_name = "TestGame"

    # Register as installed (file_path needed for _get_rom_save_info)
    plugin._state["installed_roms"]["100"] = {
        "rom_id": 100,
        "file_name": f"{rom_name}.sfc",
        "file_path": str(tmp_path / "retrodeck" / "roms" / system / f"{rom_name}.sfc"),
        "system": system,
        "platform_slug": "snes",
    }

    # Create fake save files in the fallback saves path
    saves_dir = tmp_path / "retrodeck" / "saves" / system
    saves_dir.mkdir(parents=True)
    srm = saves_dir / f"{rom_name}.srm"
    rtc = saves_dir / f"{rom_name}.rtc"
    srm.write_bytes(b"\x00" * 32)
    rtc.write_bytes(b"\x00" * 16)

    # Set up sync state
    plugin._save_sync_state["saves"]["100"] = {
        "files": {
            f"{rom_name}.srm": {"last_sync_hash": "abc123"},
            f"{rom_name}.rtc": {"last_sync_hash": "def456"},
        },
        "system": system,
    }

    result = await plugin.delete_local_saves(rom_id)
    assert result["success"] is True
    assert result["deleted_count"] == 2
    assert not srm.exists()
    assert not rtc.exists()
    assert "100" not in plugin._save_sync_state["saves"]


@pytest.mark.asyncio
async def test_delete_local_saves_no_files(plugin, tmp_path):
    """Deleting saves when none exist returns success with 0."""
    plugin._state["installed_roms"]["200"] = {
        "rom_id": 200,
        "file_name": "NoSaves.sfc",
        "file_path": str(tmp_path / "retrodeck" / "roms" / "snes" / "NoSaves.sfc"),
        "system": "snes",
        "platform_slug": "snes",
    }

    result = await plugin.delete_local_saves(200)
    assert result["success"] is True
    assert result["deleted_count"] == 0


@pytest.mark.asyncio
async def test_delete_local_saves_not_installed(plugin):
    """Deleting saves for a non-installed ROM returns success with 0."""
    result = await plugin.delete_local_saves(999)
    assert result["success"] is True
    assert result["deleted_count"] == 0


# ============================================================================
# Delete Platform Saves (Plugin callable integration)
# ============================================================================


@pytest.mark.asyncio
async def test_delete_platform_saves(plugin, tmp_path):
    """Deleting platform saves removes files for all ROMs on that platform."""
    saves_dir = tmp_path / "retrodeck" / "saves" / "snes"
    saves_dir.mkdir(parents=True)

    srm1 = saves_dir / "Game1.srm"
    srm2 = saves_dir / "Game2.srm"
    srm1.write_bytes(b"\x00" * 32)
    srm2.write_bytes(b"\x00" * 32)

    plugin._state["installed_roms"]["10"] = {
        "rom_id": 10,
        "file_name": "Game1.sfc",
        "file_path": str(tmp_path / "retrodeck" / "roms" / "snes" / "Game1.sfc"),
        "system": "snes",
        "platform_slug": "snes",
    }
    plugin._state["installed_roms"]["20"] = {
        "rom_id": 20,
        "file_name": "Game2.sfc",
        "file_path": str(tmp_path / "retrodeck" / "roms" / "snes" / "Game2.sfc"),
        "system": "snes",
        "platform_slug": "snes",
    }
    plugin._state["installed_roms"]["30"] = {
        "rom_id": 30,
        "file_name": "GBAGame.gba",
        "file_path": str(tmp_path / "retrodeck" / "roms" / "gba" / "GBAGame.gba"),
        "system": "gba",
        "platform_slug": "gba",
    }

    plugin._save_sync_state["saves"]["10"] = {"files": {"Game1.srm": {}}, "system": "snes"}
    plugin._save_sync_state["saves"]["20"] = {"files": {"Game2.srm": {}}, "system": "snes"}

    result = await plugin.delete_platform_saves("snes")
    assert result["success"] is True
    assert result["deleted_count"] == 2
    assert not srm1.exists()
    assert not srm2.exists()
    assert "10" not in plugin._save_sync_state["saves"]
    assert "20" not in plugin._save_sync_state["saves"]
