import pytest
import os
import asyncio
from unittest.mock import patch

# conftest.py patches decky before this import
from main import Plugin


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
    p._sync_running = False
    p._sync_cancel = False
    p._sync_progress = {"running": False}
    p._state = {"shortcut_registry": {}, "installed_roms": {}, "last_sync": None, "sync_stats": {}}
    p._pending_sync = {}
    p._download_tasks = {}
    p._download_queue = {}
    p._download_in_progress = set()
    p._metadata_cache = {}

    import decky
    decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)
    decky.DECKY_USER_HOME = str(tmp_path)

    p._init_save_sync_state()
    p._save_sync_state["settings"]["save_sync_enabled"] = False
    return p


@pytest.fixture(autouse=True)
async def _set_event_loop(plugin):
    plugin.loop = asyncio.get_event_loop()


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


def _server_save(save_id=100, rom_id=42, filename="pokemon.srm",
                 updated_at="2026-02-17T06:00:00Z", file_size_bytes=1024):
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
        plugin._save_sync_state["pending_conflicts"] = [
            {"rom_id": 123, "filename": "smw.srm", "local_path": "/saves/smw.srm"},
            {"rom_id": 456, "filename": "other.srm", "local_path": "/saves/other.srm"},
        ]
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
        assert len(result["pending_conflicts"]) == 1
        assert result["pending_conflicts"][0]["rom_id"] == 123
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
    async def test_no_conflicts(self, plugin):
        """No pending conflicts returns empty list."""
        plugin._state["shortcut_registry"]["10"] = {
            "app_id": 50000,
            "name": "Zelda",
            "platform_slug": "snes",
            "platform_name": "Super Nintendo",
        }
        result = await plugin.get_cached_game_detail(50000)
        assert result["found"] is True
        assert result["pending_conflicts"] == []

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
    """Test that pending_conflicts are filtered to the correct rom_id."""

    @pytest.mark.asyncio
    async def test_filters_by_rom_id(self, plugin):
        """Only conflicts matching this rom_id are returned."""
        plugin._state["shortcut_registry"]["10"] = {
            "app_id": 50000,
            "name": "Game A",
            "platform_slug": "snes",
            "platform_name": "SNES",
        }
        plugin._save_sync_state["pending_conflicts"] = [
            {"rom_id": 10, "filename": "a.srm"},
            {"rom_id": 20, "filename": "b.srm"},
            {"rom_id": 10, "filename": "c.srm"},
            {"rom_id": 30, "filename": "d.srm"},
        ]
        result = await plugin.get_cached_game_detail(50000)
        assert len(result["pending_conflicts"]) == 2
        assert all(c["rom_id"] == 10 for c in result["pending_conflicts"])
        filenames = [c["filename"] for c in result["pending_conflicts"]]
        assert "a.srm" in filenames
        assert "c.srm" in filenames

    @pytest.mark.asyncio
    async def test_no_matching_conflicts(self, plugin):
        """Conflicts exist for other roms but not this one."""
        plugin._state["shortcut_registry"]["10"] = {
            "app_id": 50000,
            "name": "Game A",
            "platform_slug": "snes",
            "platform_name": "SNES",
        }
        plugin._save_sync_state["pending_conflicts"] = [
            {"rom_id": 20, "filename": "b.srm"},
            {"rom_id": 30, "filename": "d.srm"},
        ]
        result = await plugin.get_cached_game_detail(50000)
        assert result["pending_conflicts"] == []

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
        with patch.object(plugin, "_romm_list_saves", return_value=[]):
            result = await plugin.check_save_status_lightweight(42)
        assert result["rom_id"] == 42
        assert result["files"] == []

    @pytest.mark.asyncio
    async def test_server_only_save(self, plugin, tmp_path):
        """Server save with no local file returns status=download."""
        _install_rom(plugin, tmp_path)
        server = _server_save()
        with patch.object(plugin, "_romm_list_saves", return_value=[server]):
            result = await plugin.check_save_status_lightweight(42)
        assert len(result["files"]) == 1
        assert result["files"][0]["status"] == "download"
        assert result["files"][0]["local_path"] is None
        assert result["files"][0]["server_save_id"] == 100

    @pytest.mark.asyncio
    async def test_rom_not_installed(self, plugin, tmp_path):
        """Non-installed ROM returns empty files."""
        with patch.object(plugin, "_romm_list_saves", return_value=[]):
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
        with patch.object(plugin, "_romm_list_saves", return_value=[server]):
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
        with patch.object(plugin, "_romm_list_saves", return_value=[server]):
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
        with patch.object(plugin, "_romm_list_saves", return_value=[server]):
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
        with patch.object(plugin, "_romm_list_saves", return_value=[server]):
            result = await plugin.check_save_status_lightweight(42)

        assert result["files"][0]["status"] == "conflict"


class TestLightweightSaveStatusNeverSynced:
    """Tests for saves that have never been synced (no last_sync state)."""

    @pytest.mark.asyncio
    async def test_local_only_upload(self, plugin, tmp_path):
        """Local save exists, no server save, never synced -> upload."""
        _install_rom(plugin, tmp_path)
        _create_save(tmp_path)

        with patch.object(plugin, "_romm_list_saves", return_value=[]):
            result = await plugin.check_save_status_lightweight(42)

        assert len(result["files"]) == 1
        assert result["files"][0]["status"] == "upload"

    @pytest.mark.asyncio
    async def test_both_exist_never_synced_conflict(self, plugin, tmp_path):
        """Both local and server exist but never synced -> conflict."""
        _install_rom(plugin, tmp_path)
        _create_save(tmp_path)

        server = _server_save()
        with patch.object(plugin, "_romm_list_saves", return_value=[server]):
            result = await plugin.check_save_status_lightweight(42)

        assert result["files"][0]["status"] == "conflict"


class TestLightweightSaveStatusAPIError:
    """Tests for server API errors."""

    @pytest.mark.asyncio
    async def test_api_error_local_files_only(self, plugin, tmp_path):
        """API error still returns local files with upload status."""
        _install_rom(plugin, tmp_path)
        _create_save(tmp_path)

        with patch.object(plugin, "_with_retry", side_effect=Exception("Connection refused")):
            result = await plugin.check_save_status_lightweight(42)

        assert len(result["files"]) == 1
        assert result["files"][0]["filename"] == "pokemon.srm"
        assert result["files"][0]["status"] == "upload"
        assert result["files"][0]["server_save_id"] is None
