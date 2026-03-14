import asyncio
import logging
import os
from unittest.mock import MagicMock

import pytest
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
    p._state = {"shortcut_registry": {}, "installed_roms": {}, "last_sync": None, "sync_stats": {}}
    p._metadata_cache = {}

    import decky

    decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

    steam_config = SteamConfigAdapter(user_home=decky.DECKY_USER_HOME, logger=decky.logger)
    p._steam_config = steam_config

    p._sync_service = SyncService(
        http_client=MagicMock(),
        steam_config=steam_config,
        state=p._state,
        settings=p.settings,
        metadata_cache=p._metadata_cache,
        loop=asyncio.get_event_loop(),
        logger=decky.logger,
        plugin_dir=decky.DECKY_PLUGIN_DIR,
        emit=decky.emit,
        save_state=p._save_state,
        save_settings_to_disk=p._save_settings_to_disk,
        log_debug=p._log_debug,
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

    p._save_sync_state["settings"]["save_sync_enabled"] = False
    return p


@pytest.fixture(autouse=True)
async def _set_event_loop(plugin):
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
    """Helper: build a server save response dict."""
    return {
        "id": save_id,
        "rom_id": rom_id,
        "file_name": filename,
        "updated_at": updated_at,
        "file_size_bytes": file_size_bytes,
        "emulator": "retroarch",
        "download_path": f"/saves/{filename}",
    }


class TestGetCachedGameDetailFound:
    """Test get_cached_game_detail when app_id is in the registry."""

    @pytest.mark.asyncio
    async def test_found_with_full_data(self, plugin):
        """All data present: registry, installed, save status, metadata, conflicts."""
        plugin._state["shortcut_registry"]["123"] = {
            "app_id": 99999,
            "name": "Super Mario World",
            "platform_slug": "snes",
            "platform_name": "Super Nintendo",
        }
        plugin._state["installed_roms"]["123"] = {
            "rom_id": 123,
            "file_path": "/roms/snes/smw.sfc",
            "system": "snes",
        }
        plugin._save_sync_state["settings"]["save_sync_enabled"] = True
        plugin._save_sync_state["saves"]["123"] = {
            "files": {
                "smw.srm": {
                    "last_sync_at": "2025-01-01T00:00:00Z",
                    "last_sync_hash": "abc123",
                },
            },
            "last_sync_check_at": "2025-01-01T00:00:00Z",
        }
        plugin._metadata_cache["123"] = {
            "summary": "Classic SNES platformer",
            "genres": ["Platformer"],
            "cached_at": 100,
        }

        result = await plugin.get_cached_game_detail(99999)

        assert result["found"] is True
        assert result["rom_id"] == 123
        assert result["rom_name"] == "Super Mario World"
        assert result["platform_slug"] == "snes"
        assert result["platform_name"] == "Super Nintendo"
        assert result["installed"] is True
        assert result["save_sync_enabled"] is True
        assert len(result["save_status"]["files"]) == 1
        assert result["save_status"]["files"][0]["filename"] == "smw.srm"
        assert result["save_status"]["files"][0]["status"] == "synced"
        assert result["save_status"]["last_sync_check_at"] == "2025-01-01T00:00:00Z"
        assert result["metadata"]["summary"] == "Classic SNES platformer"
        assert result["bios_status"] is None


class TestGetCachedGameDetailNotFound:
    """Test get_cached_game_detail when app_id is NOT in the registry."""

    @pytest.mark.asyncio
    async def test_not_found(self, plugin):
        """Unknown app_id returns found=False."""
        result = await plugin.get_cached_game_detail(12345)
        assert result == {"found": False}

    @pytest.mark.asyncio
    async def test_not_found_empty_registry(self, plugin):
        """Empty registry returns found=False."""
        plugin._state["shortcut_registry"] = {}
        result = await plugin.get_cached_game_detail(1)
        assert result == {"found": False}

    @pytest.mark.asyncio
    async def test_not_found_different_app_id(self, plugin):
        """Registry has entries but none match the requested app_id."""
        plugin._state["shortcut_registry"]["10"] = {
            "app_id": 11111,
            "name": "Other Game",
            "platform_slug": "nes",
            "platform_name": "NES",
        }
        result = await plugin.get_cached_game_detail(99999)
        assert result == {"found": False}


class TestGetCachedGameDetailPartialData:
    """Test with missing optional data (no save status, no metadata, etc.)."""

    @pytest.mark.asyncio
    async def test_no_save_status(self, plugin):
        """No save data for this rom returns save_status=None."""
        plugin._state["shortcut_registry"]["10"] = {
            "app_id": 50000,
            "name": "Zelda",
            "platform_slug": "snes",
            "platform_name": "Super Nintendo",
        }
        result = await plugin.get_cached_game_detail(50000)
        assert result["found"] is True
        assert result["save_status"] is None

    @pytest.mark.asyncio
    async def test_no_metadata(self, plugin):
        """No metadata cached returns metadata=None."""
        plugin._state["shortcut_registry"]["10"] = {
            "app_id": 50000,
            "name": "Zelda",
            "platform_slug": "snes",
            "platform_name": "Super Nintendo",
        }
        result = await plugin.get_cached_game_detail(50000)
        assert result["found"] is True
        assert result["metadata"] is None

    @pytest.mark.asyncio
    async def test_no_pending_conflicts_key(self, plugin):
        """pending_conflicts is no longer in the response (conflicts are inline)."""
        plugin._state["shortcut_registry"]["10"] = {
            "app_id": 50000,
            "name": "Zelda",
            "platform_slug": "snes",
            "platform_name": "Super Nintendo",
        }
        result = await plugin.get_cached_game_detail(50000)
        assert result["found"] is True
        assert "pending_conflicts" not in result

    @pytest.mark.asyncio
    async def test_save_sync_disabled(self, plugin):
        """save_sync_enabled reflects the setting."""
        plugin._state["shortcut_registry"]["10"] = {
            "app_id": 50000,
            "name": "Zelda",
            "platform_slug": "snes",
            "platform_name": "Super Nintendo",
        }
        plugin._save_sync_state["settings"]["save_sync_enabled"] = False
        result = await plugin.get_cached_game_detail(50000)
        assert result["save_sync_enabled"] is False

    @pytest.mark.asyncio
    async def test_missing_registry_fields_default_empty(self, plugin):
        """Registry entry missing optional fields returns empty strings."""
        plugin._state["shortcut_registry"]["10"] = {
            "app_id": 50000,
        }
        result = await plugin.get_cached_game_detail(50000)
        assert result["found"] is True
        assert result["rom_name"] == ""
        assert result["platform_slug"] == ""
        assert result["platform_name"] == ""


class TestGetCachedGameDetailInstalled:
    """Test installed vs not installed detection."""

    @pytest.mark.asyncio
    async def test_installed(self, plugin):
        """ROM in installed_roms returns installed=True."""
        plugin._state["shortcut_registry"]["10"] = {
            "app_id": 50000,
            "name": "Game",
            "platform_slug": "snes",
            "platform_name": "SNES",
        }
        plugin._state["installed_roms"]["10"] = {
            "rom_id": 10,
            "file_path": "/roms/game.sfc",
        }
        result = await plugin.get_cached_game_detail(50000)
        assert result["installed"] is True

    @pytest.mark.asyncio
    async def test_not_installed(self, plugin):
        """ROM not in installed_roms returns installed=False."""
        plugin._state["shortcut_registry"]["10"] = {
            "app_id": 50000,
            "name": "Game",
            "platform_slug": "snes",
            "platform_name": "SNES",
        }
        result = await plugin.get_cached_game_detail(50000)
        assert result["installed"] is False


class TestGetCachedGameDetailConflictFiltering:
    """pending_conflicts was removed from get_cached_game_detail response."""

    @pytest.mark.asyncio
    async def test_no_pending_conflicts_in_response(self, plugin):
        """pending_conflicts key is no longer in the response."""
        plugin._state["shortcut_registry"]["10"] = {
            "app_id": 50000,
            "name": "Game A",
            "platform_slug": "snes",
            "platform_name": "SNES",
        }
        result = await plugin.get_cached_game_detail(50000)
        assert "pending_conflicts" not in result

    @pytest.mark.asyncio
    async def test_response_still_has_save_status(self, plugin):
        """Response still includes save status fields."""
        plugin._state["shortcut_registry"]["10"] = {
            "app_id": 50000,
            "name": "Game A",
            "platform_slug": "snes",
            "platform_name": "SNES",
        }
        result = await plugin.get_cached_game_detail(50000)
        assert result["found"] is True
        assert "save_sync_enabled" in result

    @pytest.mark.asyncio
    async def test_app_id_as_string(self, plugin):
        """app_id passed as string is handled correctly."""
        plugin._state["shortcut_registry"]["10"] = {
            "app_id": 50000,
            "name": "Game",
            "platform_slug": "snes",
            "platform_name": "SNES",
        }
        result = await plugin.get_cached_game_detail("50000")
        assert result["found"] is True
        assert result["rom_id"] == 10


# ============================================================================
# check_save_status_lightweight tests
# ============================================================================


class TestLightweightSaveStatusNoSaves:
    """Tests when ROM has no save files."""

    @pytest.mark.asyncio
    async def test_no_local_no_server(self, plugin, tmp_path):
        """No local or server saves returns empty files list."""
        _install_rom(plugin, tmp_path)
        result = await plugin.check_save_status_lightweight(42)
        assert result["rom_id"] == 42
        assert result["files"] == []

    @pytest.mark.asyncio
    async def test_server_only_save(self, plugin, tmp_path):
        """Server save with no local file returns status=download."""
        _install_rom(plugin, tmp_path)
        server = _server_save()
        plugin._fake_api.saves[server["id"]] = server
        result = await plugin.check_save_status_lightweight(42)
        assert len(result["files"]) == 1
        assert result["files"][0]["status"] == "download"
        assert result["files"][0]["local_path"] is None
        assert result["files"][0]["server_save_id"] == 100

    @pytest.mark.asyncio
    async def test_rom_not_installed(self, plugin, tmp_path):
        """Non-installed ROM returns empty files."""
        result = await plugin.check_save_status_lightweight(999)
        assert result["files"] == []


class TestLightweightSaveStatusSynced:
    """Tests for previously-synced saves (have last_sync state)."""

    @pytest.mark.asyncio
    async def test_no_changes_skip(self, plugin, tmp_path):
        """Local and server unchanged since last sync -> skip."""
        _install_rom(plugin, tmp_path)
        save_file = _create_save(tmp_path)
        save_mtime = os.path.getmtime(str(save_file))

        plugin._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": "abc123",
                    "last_sync_local_mtime": save_mtime,
                    "last_sync_local_size": 1024,
                    "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
                    "last_sync_server_size": 1024,
                    "last_sync_at": "2026-02-17T08:00:00Z",
                },
            },
        }

        server = _server_save()
        plugin._fake_api.saves[server["id"]] = server
        result = await plugin.check_save_status_lightweight(42)

        assert len(result["files"]) == 1
        assert result["files"][0]["status"] == "skip"
        assert result["files"][0]["local_hash"] is None

    @pytest.mark.asyncio
    async def test_server_changed_download(self, plugin, tmp_path):
        """Server updated_at changed since last sync -> download."""
        _install_rom(plugin, tmp_path)
        save_file = _create_save(tmp_path)
        save_mtime = os.path.getmtime(str(save_file))

        plugin._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": "abc123",
                    "last_sync_local_mtime": save_mtime,
                    "last_sync_local_size": 1024,
                    "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
                    "last_sync_server_size": 1024,
                },
            },
        }

        server = _server_save(updated_at="2026-02-18T10:00:00Z")
        plugin._fake_api.saves[server["id"]] = server
        result = await plugin.check_save_status_lightweight(42)

        assert result["files"][0]["status"] == "download"

    @pytest.mark.asyncio
    async def test_local_changed_upload(self, plugin, tmp_path):
        """Local mtime changed since last sync, server unchanged -> upload."""
        _install_rom(plugin, tmp_path)
        save_file = _create_save(tmp_path)

        plugin._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": "abc123",
                    "last_sync_local_mtime": os.path.getmtime(str(save_file)) - 100,
                    "last_sync_local_size": 1024,
                    "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
                    "last_sync_server_size": 1024,
                },
            },
        }

        server = _server_save()
        plugin._fake_api.saves[server["id"]] = server
        result = await plugin.check_save_status_lightweight(42)

        assert result["files"][0]["status"] == "upload"

    @pytest.mark.asyncio
    async def test_both_changed_conflict(self, plugin, tmp_path):
        """Both local and server changed -> conflict."""
        _install_rom(plugin, tmp_path)
        save_file = _create_save(tmp_path)

        plugin._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": "abc123",
                    "last_sync_local_mtime": os.path.getmtime(str(save_file)) - 100,
                    "last_sync_local_size": 1024,
                    "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
                    "last_sync_server_size": 1024,
                },
            },
        }

        server = _server_save(updated_at="2026-02-18T10:00:00Z")
        plugin._fake_api.saves[server["id"]] = server
        result = await plugin.check_save_status_lightweight(42)

        assert result["files"][0]["status"] == "conflict"


class TestLightweightSaveStatusNeverSynced:
    """Tests for saves that have never been synced (no last_sync state)."""

    @pytest.mark.asyncio
    async def test_local_only_upload(self, plugin, tmp_path):
        """Local save exists, no server save, never synced -> upload."""
        _install_rom(plugin, tmp_path)
        _create_save(tmp_path)

        result = await plugin.check_save_status_lightweight(42)

        assert len(result["files"]) == 1
        assert result["files"][0]["status"] == "upload"

    @pytest.mark.asyncio
    async def test_both_exist_never_synced_conflict(self, plugin, tmp_path):
        """Both local and server exist but never synced -> conflict."""
        _install_rom(plugin, tmp_path)
        _create_save(tmp_path)

        server = _server_save()
        plugin._fake_api.saves[server["id"]] = server
        result = await plugin.check_save_status_lightweight(42)

        assert result["files"][0]["status"] == "conflict"


class TestLightweightSaveStatusAPIError:
    """Tests for server API errors."""

    @pytest.mark.asyncio
    async def test_api_error_local_files_only(self, plugin, tmp_path):
        """API error still returns local files with upload status."""
        _install_rom(plugin, tmp_path)
        _create_save(tmp_path)

        plugin._fake_api.fail_on_next(Exception("Connection refused"))
        result = await plugin.check_save_status_lightweight(42)

        assert len(result["files"]) == 1
        assert result["files"][0]["filename"] == "pokemon.srm"
        assert result["files"][0]["status"] == "upload"
        assert result["files"][0]["server_save_id"] is None
