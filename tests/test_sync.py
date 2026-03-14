import asyncio
import os
from unittest.mock import MagicMock

import pytest
from adapters.steam_config import SteamConfigAdapter
from services.metadata import MetadataService
from services.sync import SyncService, SyncState

# conftest.py patches decky before this import
from main import Plugin


@pytest.fixture
def plugin():
    p = Plugin()
    p.settings = {"romm_url": "", "romm_user": "", "romm_pass": "", "enabled_platforms": {}}
    p._http_client = MagicMock()
    p._state = {"shortcut_registry": {}, "installed_roms": {}, "last_sync": None, "sync_stats": {}}
    p._metadata_cache = {}

    import decky

    steam_config = SteamConfigAdapter(user_home=decky.DECKY_USER_HOME, logger=decky.logger)
    p._steam_config = steam_config

    metadata_service = MetadataService(
        http_client=p._http_client,
        state=p._state,
        metadata_cache=p._metadata_cache,
        loop=asyncio.get_event_loop(),
        logger=decky.logger,
        save_metadata_cache=p._save_metadata_cache,
        log_debug=p._log_debug,
    )
    p._metadata_service = metadata_service

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
        save_state=p._save_state,
        save_settings_to_disk=p._save_settings_to_disk,
        log_debug=p._log_debug,
        metadata_service=metadata_service,
    )
    return p


@pytest.fixture(autouse=True)
async def _set_event_loop(plugin):
    """Ensure plugin.loop matches the running event loop for async tests."""
    plugin.loop = asyncio.get_event_loop()
    plugin._sync_service._loop = asyncio.get_event_loop()
    plugin._metadata_service._loop = asyncio.get_event_loop()


class TestReportSyncResults:
    @pytest.mark.asyncio
    async def test_updates_registry(self, plugin, tmp_path):
        import decky

        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._sync_service._pending_sync = {
            1: {"name": "Game A", "platform_name": "N64", "cover_path": "/grid/abc.png"},
            2: {"name": "Game B", "platform_name": "SNES", "cover_path": "/grid/def.png"},
        }

        result = await plugin.report_sync_results(
            {"1": 100001, "2": 100002},
            [],
        )
        assert result["success"] is True
        assert "1" in plugin._state["shortcut_registry"]
        assert plugin._state["shortcut_registry"]["1"]["app_id"] == 100001
        assert plugin._state["shortcut_registry"]["1"]["name"] == "Game A"
        assert plugin._state["shortcut_registry"]["1"]["platform_name"] == "N64"
        assert "2" in plugin._state["shortcut_registry"]

    @pytest.mark.asyncio
    async def test_removes_stale_entries(self, plugin, tmp_path):
        import decky

        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._state["shortcut_registry"]["99"] = {
            "app_id": 99999,
            "name": "Old Game",
            "platform_name": "NES",
        }
        plugin._sync_service._pending_sync = {}

        result = await plugin.report_sync_results({}, [99])
        assert result["success"] is True
        assert "99" not in plugin._state["shortcut_registry"]

    @pytest.mark.asyncio
    async def test_emits_sync_complete(self, plugin, tmp_path):
        import decky

        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)
        decky.emit.reset_mock()

        plugin._sync_service._pending_sync = {
            1: {"name": "Game A", "platform_name": "N64", "cover_path": ""},
        }

        await plugin.report_sync_results({"1": 100001}, [])
        # emit called twice: sync_complete then sync_progress (done)
        assert decky.emit.call_count == 2
        sync_complete_call = decky.emit.call_args_list[0]
        assert sync_complete_call[0][0] == "sync_complete"
        assert sync_complete_call[0][1]["total_games"] == 1

    @pytest.mark.asyncio
    async def test_updates_last_sync(self, plugin, tmp_path):
        import decky

        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._sync_service._pending_sync = {}
        await plugin.report_sync_results({}, [])
        assert plugin._state["last_sync"] is not None

    @pytest.mark.asyncio
    async def test_clears_pending_sync(self, plugin, tmp_path):
        import decky

        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._sync_service._pending_sync = {1: {"name": "X", "platform_name": "Y", "cover_path": ""}}
        await plugin.report_sync_results({"1": 1}, [])
        assert plugin._sync_service._pending_sync == {}


class TestRemoveAllShortcuts:
    @pytest.mark.asyncio
    async def test_returns_app_ids_and_rom_ids(self, plugin):
        plugin._state["shortcut_registry"] = {
            "10": {"app_id": 1001, "name": "Game A"},
            "20": {"app_id": 1002, "name": "Game B"},
            "30": {"name": "Game C"},  # no app_id (edge case)
        }

        result = await plugin.remove_all_shortcuts()
        assert result["success"] is True
        assert set(result["app_ids"]) == {1001, 1002}
        assert set(result["rom_ids"]) == {"10", "20", "30"}

    @pytest.mark.asyncio
    async def test_empty_registry(self, plugin):
        result = await plugin.remove_all_shortcuts()
        assert result["success"] is True
        assert result["app_ids"] == []
        assert result["rom_ids"] == []

    @pytest.mark.asyncio
    async def test_does_not_modify_registry(self, plugin):
        """remove_all_shortcuts just returns data; registry cleared by report_removal_results."""
        plugin._state["shortcut_registry"] = {
            "10": {"app_id": 1001, "name": "Game A"},
        }
        await plugin.remove_all_shortcuts()
        # Registry should NOT be cleared yet
        assert "10" in plugin._state["shortcut_registry"]


class TestReportRemovalResults:
    @pytest.mark.asyncio
    async def test_removes_entries_from_registry(self, plugin, tmp_path):
        import decky

        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._state["shortcut_registry"] = {
            "10": {"app_id": 1001, "name": "Game A", "cover_path": ""},
            "20": {"app_id": 1002, "name": "Game B", "cover_path": ""},
        }

        result = await plugin.report_removal_results([10, 20])
        assert result["success"] is True
        assert plugin._state["shortcut_registry"] == {}

    @pytest.mark.asyncio
    async def test_cleans_up_artwork_cover_path(self, plugin, tmp_path):
        import decky

        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)
        decky.DECKY_USER_HOME = str(tmp_path)

        # Create a fake artwork file
        art_file = tmp_path / "cover.png"
        art_file.write_text("fake")

        plugin._state["shortcut_registry"] = {
            "10": {"app_id": 1001, "name": "Game A", "cover_path": str(art_file)},
        }
        # Mock _grid_dir to return tmp_path
        plugin._steam_config.grid_dir = lambda: str(tmp_path)

        result = await plugin.report_removal_results([10])
        assert result["success"] is True
        assert not art_file.exists()

    @pytest.mark.asyncio
    async def test_cleans_up_artwork_legacy_id(self, plugin, tmp_path):
        import decky

        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        grid_dir = tmp_path / "grid"
        grid_dir.mkdir()
        art_file = grid_dir / "12345p.png"
        art_file.write_text("fake")

        plugin._state["shortcut_registry"] = {
            "10": {"app_id": 1001, "name": "Game A", "artwork_id": 12345},
        }
        plugin._steam_config.grid_dir = lambda: str(grid_dir)

        result = await plugin.report_removal_results([10])
        assert result["success"] is True
        assert not art_file.exists()

    @pytest.mark.asyncio
    async def test_partial_removal(self, plugin, tmp_path):
        import decky

        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._state["shortcut_registry"] = {
            "10": {"app_id": 1001, "name": "Game A", "cover_path": ""},
            "20": {"app_id": 1002, "name": "Game B", "cover_path": ""},
        }

        result = await plugin.report_removal_results([10])
        assert result["success"] is True
        assert "10" not in plugin._state["shortcut_registry"]
        assert "20" in plugin._state["shortcut_registry"]


class TestGetSyncStats:
    @pytest.mark.asyncio
    async def test_computes_from_registry(self, plugin):
        plugin._state["shortcut_registry"] = {
            "10": {"app_id": 1001, "name": "Game A", "platform_name": "N64"},
            "20": {"app_id": 1002, "name": "Game B", "platform_name": "N64"},
            "30": {"app_id": 1003, "name": "Game C", "platform_name": "SNES"},
        }
        plugin._state["last_sync"] = "2025-01-01T00:00:00"

        stats = await plugin.get_sync_stats()
        assert stats["platforms"] == 2
        assert stats["roms"] == 3
        assert stats["total_shortcuts"] == 3
        assert stats["last_sync"] == "2025-01-01T00:00:00"

    @pytest.mark.asyncio
    async def test_empty_registry(self, plugin):
        stats = await plugin.get_sync_stats()
        assert stats["platforms"] == 0
        assert stats["roms"] == 0
        assert stats["total_shortcuts"] == 0

    @pytest.mark.asyncio
    async def test_updates_after_removal(self, plugin, tmp_path):
        """Stats should reflect registry changes after report_removal_results."""
        import decky

        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._state["shortcut_registry"] = {
            "10": {"app_id": 1001, "name": "Game A", "platform_name": "N64", "cover_path": ""},
            "20": {"app_id": 1002, "name": "Game B", "platform_name": "SNES", "cover_path": ""},
        }

        await plugin.report_removal_results([10])
        stats = await plugin.get_sync_stats()
        assert stats["platforms"] == 1
        assert stats["roms"] == 1
        assert stats["total_shortcuts"] == 1

    @pytest.mark.asyncio
    async def test_report_removal_updates_sync_stats_state(self, plugin, tmp_path):
        """report_removal_results should update sync_stats in state."""
        import decky

        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._state["shortcut_registry"] = {
            "10": {"app_id": 1001, "name": "Game A", "platform_name": "N64", "cover_path": ""},
            "20": {"app_id": 1002, "name": "Game B", "platform_name": "SNES", "cover_path": ""},
        }

        await plugin.report_removal_results([10, 20])
        assert plugin._state["sync_stats"]["platforms"] == 0
        assert plugin._state["sync_stats"]["roms"] == 0


class TestGetRegistryPlatforms:
    @pytest.mark.asyncio
    async def test_returns_platforms_from_registry(self, plugin):
        plugin._state["shortcut_registry"] = {
            "10": {"app_id": 1001, "name": "Mario 64", "platform_name": "Nintendo 64", "platform_slug": "n64"},
            "20": {"app_id": 1002, "name": "Zelda OOT", "platform_name": "Nintendo 64", "platform_slug": "n64"},
            "30": {"app_id": 1003, "name": "DKC", "platform_name": "Super Nintendo", "platform_slug": "snes"},
        }

        result = await plugin.get_registry_platforms()
        assert len(result["platforms"]) == 2
        # Sorted by name
        assert result["platforms"][0]["name"] == "Nintendo 64"
        assert result["platforms"][0]["slug"] == "n64"
        assert result["platforms"][0]["count"] == 2
        assert result["platforms"][1]["name"] == "Super Nintendo"
        assert result["platforms"][1]["slug"] == "snes"
        assert result["platforms"][1]["count"] == 1

    @pytest.mark.asyncio
    async def test_empty_registry(self, plugin):
        result = await plugin.get_registry_platforms()
        assert result["platforms"] == []

    @pytest.mark.asyncio
    async def test_missing_platform_slug(self, plugin):
        """Old entries without platform_slug should still appear with empty slug."""
        plugin._state["shortcut_registry"] = {
            "10": {"app_id": 1001, "name": "Mario 64", "platform_name": "Nintendo 64"},
        }

        result = await plugin.get_registry_platforms()
        assert len(result["platforms"]) == 1
        assert result["platforms"][0]["name"] == "Nintendo 64"
        assert result["platforms"][0]["slug"] == ""
        assert result["platforms"][0]["count"] == 1


class TestRemovePlatformShortcuts:
    @pytest.mark.asyncio
    async def test_returns_matching_platform_entries(self, plugin):
        from unittest.mock import AsyncMock, MagicMock

        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(
            return_value=[
                {"id": 1, "slug": "n64", "name": "Nintendo 64"},
                {"id": 2, "slug": "snes", "name": "Super Nintendo"},
            ]
        )
        plugin._sync_service._loop = mock_loop

        plugin._state["shortcut_registry"] = {
            "10": {"app_id": 1001, "name": "Mario 64", "platform_name": "Nintendo 64"},
            "20": {"app_id": 1002, "name": "Zelda OOT", "platform_name": "Nintendo 64"},
            "30": {"app_id": 1003, "name": "DKC", "platform_name": "Super Nintendo"},
        }

        result = await plugin.remove_platform_shortcuts("n64")
        assert result["success"] is True
        assert set(result["app_ids"]) == {1001, 1002}
        assert set(result["rom_ids"]) == {"10", "20"}
        assert result["platform_name"] == "Nintendo 64"

    @pytest.mark.asyncio
    async def test_platform_not_found(self, plugin):
        from unittest.mock import AsyncMock, MagicMock

        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(
            return_value=[
                {"id": 1, "slug": "n64", "name": "Nintendo 64"},
            ]
        )
        plugin._sync_service._loop = mock_loop

        result = await plugin.remove_platform_shortcuts("nonexistent")
        assert result["success"] is False
        assert result["app_ids"] == []
        assert result["rom_ids"] == []

    @pytest.mark.asyncio
    async def test_does_not_modify_registry(self, plugin):
        """remove_platform_shortcuts just returns data; registry cleared by report_removal_results."""
        from unittest.mock import AsyncMock, MagicMock

        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(
            return_value=[
                {"id": 1, "slug": "n64", "name": "Nintendo 64"},
            ]
        )
        plugin._sync_service._loop = mock_loop

        plugin._state["shortcut_registry"] = {
            "10": {"app_id": 1001, "name": "Mario 64", "platform_name": "Nintendo 64"},
        }

        await plugin.remove_platform_shortcuts("n64")
        # Registry should NOT be modified yet
        assert "10" in plugin._state["shortcut_registry"]

    @pytest.mark.asyncio
    async def test_works_offline_with_registry_slug(self, plugin):
        """When platform_slug is in the registry, no API call needed."""
        from unittest.mock import AsyncMock, MagicMock

        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(side_effect=Exception("Server unreachable"))
        plugin._sync_service._loop = mock_loop

        plugin._state["shortcut_registry"] = {
            "10": {"app_id": 1001, "name": "Mario 64", "platform_name": "Nintendo 64", "platform_slug": "n64"},
            "20": {"app_id": 1002, "name": "Zelda OOT", "platform_name": "Nintendo 64", "platform_slug": "n64"},
        }

        result = await plugin.remove_platform_shortcuts("n64")
        assert result["success"] is True
        assert set(result["app_ids"]) == {1001, 1002}
        assert result["platform_name"] == "Nintendo 64"


class TestArtworkStaging:
    """Tests for the staging/rename artwork flow."""

    @pytest.mark.asyncio
    async def test_download_uses_staging_filename(self, plugin, tmp_path):
        from unittest.mock import AsyncMock, MagicMock

        grid_dir = tmp_path / "grid"
        grid_dir.mkdir()
        plugin._steam_config.grid_dir = lambda: str(grid_dir)
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock()
        plugin._sync_service._loop = mock_loop

        roms = [{"id": 42, "name": "Test Game", "path_cover_large": "/cover.png"}]
        result = await plugin._sync_service._download_artwork(roms)

        assert 42 in result
        assert result[42].endswith("romm_42_cover.png")
        # Should have called _romm_download with staging path as dest arg
        call_args = mock_loop.run_in_executor.call_args[0]
        assert "romm_42_cover.png" in call_args[3]

    @pytest.mark.asyncio
    async def test_skips_download_if_final_exists(self, plugin, tmp_path):
        """If {app_id}p.png exists from a prior sync, skip re-download."""
        from unittest.mock import AsyncMock, MagicMock

        grid_dir = tmp_path / "grid"
        grid_dir.mkdir()
        plugin._steam_config.grid_dir = lambda: str(grid_dir)
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock()
        plugin._sync_service._loop = mock_loop

        # Simulate existing final artwork from previous sync
        final_art = grid_dir / "99999p.png"
        final_art.write_text("fake")

        plugin._state["shortcut_registry"]["42"] = {"app_id": 99999, "name": "Test"}

        roms = [{"id": 42, "name": "Test Game", "path_cover_large": "/cover.png"}]
        result = await plugin._sync_service._download_artwork(roms)

        assert result[42] == str(final_art)
        mock_loop.run_in_executor.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_download_if_staging_exists(self, plugin, tmp_path):
        """If staging file exists (e.g. retry), skip re-download."""
        from unittest.mock import AsyncMock, MagicMock

        grid_dir = tmp_path / "grid"
        grid_dir.mkdir()
        plugin._steam_config.grid_dir = lambda: str(grid_dir)
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock()
        plugin._sync_service._loop = mock_loop

        staging = grid_dir / "romm_42_cover.png"
        staging.write_text("fake")

        roms = [{"id": 42, "name": "Test Game", "path_cover_large": "/cover.png"}]
        result = await plugin._sync_service._download_artwork(roms)

        assert result[42] == str(staging)
        mock_loop.run_in_executor.assert_not_called()


class TestArtworkRenameOnSync:
    """Tests for artwork rename in report_sync_results."""

    @pytest.mark.asyncio
    async def test_renames_staged_to_app_id(self, plugin, tmp_path):
        import decky

        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        grid_dir = tmp_path / "grid"
        grid_dir.mkdir()
        plugin._steam_config.grid_dir = lambda: str(grid_dir)

        # Create staged artwork
        staging = grid_dir / "romm_1_cover.png"
        staging.write_text("cover data")

        plugin._sync_service._pending_sync = {
            1: {"name": "Game A", "platform_name": "N64", "cover_path": str(staging)},
        }

        await plugin.report_sync_results({"1": 100001}, [])

        # Staging file should be gone, final file should exist
        assert not staging.exists()
        final = grid_dir / "100001p.png"
        assert final.exists()
        assert final.read_text() == "cover data"

        # Registry should store the final path
        entry = plugin._state["shortcut_registry"]["1"]
        assert entry["cover_path"] == str(final)

    @pytest.mark.asyncio
    async def test_handles_already_final_artwork(self, plugin, tmp_path):
        """If cover_path already points to the final file, don't error."""
        import decky

        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        grid_dir = tmp_path / "grid"
        grid_dir.mkdir()
        plugin._steam_config.grid_dir = lambda: str(grid_dir)

        final = grid_dir / "100001p.png"
        final.write_text("cover data")

        plugin._sync_service._pending_sync = {
            1: {"name": "Game A", "platform_name": "N64", "cover_path": str(final)},
        }

        await plugin.report_sync_results({"1": 100001}, [])

        assert final.exists()
        entry = plugin._state["shortcut_registry"]["1"]
        assert entry["cover_path"] == str(final)


class TestRemovalCleansUpAppIdArtwork:
    """Tests for app_id-based artwork cleanup in report_removal_results."""

    @pytest.mark.asyncio
    async def test_removes_app_id_artwork(self, plugin, tmp_path):
        import decky

        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        grid_dir = tmp_path / "grid"
        grid_dir.mkdir()
        art_file = grid_dir / "100001p.png"
        art_file.write_text("fake")

        plugin._state["shortcut_registry"] = {
            "10": {"app_id": 100001, "name": "Game A", "cover_path": ""},
        }
        plugin._steam_config.grid_dir = lambda: str(grid_dir)

        await plugin.report_removal_results([10])
        assert not art_file.exists()

    @pytest.mark.asyncio
    async def test_removes_staging_leftover(self, plugin, tmp_path):
        import decky

        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        grid_dir = tmp_path / "grid"
        grid_dir.mkdir()
        staging = grid_dir / "romm_10_cover.png"
        staging.write_text("fake")

        plugin._state["shortcut_registry"] = {
            "10": {"app_id": 100001, "name": "Game A", "cover_path": ""},
        }
        plugin._steam_config.grid_dir = lambda: str(grid_dir)

        await plugin.report_removal_results([10])
        assert not staging.exists()


class TestGetRomBySteamAppId:
    @pytest.mark.asyncio
    async def test_finds_rom_by_app_id(self, plugin):
        plugin._state["shortcut_registry"]["42"] = {
            "app_id": 100001,
            "name": "Zelda",
            "platform_name": "N64",
            "platform_slug": "n64",
        }
        plugin._state["installed_roms"]["42"] = {
            "rom_id": 42,
            "file_path": "/roms/n64/zelda.z64",
        }
        result = await plugin.get_rom_by_steam_app_id(100001)
        assert result is not None
        assert result["rom_id"] == 42
        assert result["name"] == "Zelda"
        assert result["installed"] is not None

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown(self, plugin):
        result = await plugin.get_rom_by_steam_app_id(999999)
        assert result is None


class TestShortcutDataFormat:
    """Validate the shortcut data format produced by the backend.

    The backend prepares shortcut data that the frontend uses to create
    Steam shortcuts. These tests ensure the data is well-formed.
    """

    @pytest.mark.asyncio
    async def test_shortcut_data_has_required_fields(self, plugin):
        """Every shortcut entry must have all required fields."""
        from unittest.mock import AsyncMock, MagicMock

        plugin.settings["romm_url"] = "http://romm.local"
        plugin.settings["enabled_platforms"] = {"gba": True}
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(
            side_effect=[
                # _fetch_platforms
                [{"id": 1, "slug": "gba", "name": "Game Boy Advance", "rom_count": 1}],
                # _fetch_roms_for_platform
                [
                    {
                        "id": 42,
                        "name": "Test Game",
                        "platform_name": "Game Boy Advance",
                        "platform_slug": "gba",
                        "igdb_id": 100,
                        "sgdb_id": 200,
                        "path_cover_large": "/cover.png",
                    }
                ],
            ]
        )
        plugin._sync_service._loop = mock_loop
        plugin._sync_service._download_artwork = AsyncMock(return_value={})
        plugin._sync_service._emit_progress = AsyncMock()
        plugin._sync_service._sync_state = SyncState.IDLE

        # Mock decky.emit to capture the shortcuts
        import decky

        emitted_events = []
        original_emit = getattr(decky, "emit", None)

        async def mock_emit(event, *args):
            emitted_events.append((event, args))

        decky.emit = mock_emit
        plugin._sync_service._emit = mock_emit

        try:
            # Call _do_sync directly (start_sync creates a background task
            # that never runs with a mock loop)
            await plugin._sync_service._do_sync()
        except Exception:
            pass
        finally:
            if original_emit:
                decky.emit = original_emit

        # Find the sync_apply emission
        sync_items = None
        for event, args in emitted_events:
            if event == "sync_apply" and args:
                sync_items = args[0] if args else None
                break

        assert sync_items is not None, "sync_apply event should have been emitted"
        required_fields = {"rom_id", "name", "exe", "start_dir", "launch_options", "platform_name", "platform_slug"}
        for item in sync_items.get("shortcuts", sync_items):
            for field in required_fields:
                assert field in item, f"Missing field '{field}' in shortcut data"

    @pytest.mark.asyncio
    async def test_exe_path_points_to_romm_launcher(self, plugin):
        """Exe path must point to bin/romm-launcher inside the plugin directory."""
        import decky

        plugin.settings["romm_url"] = "http://romm.local"
        exe = os.path.join(decky.DECKY_PLUGIN_DIR, "bin", "romm-launcher")

        assert exe.endswith("/bin/romm-launcher"), f"Exe path should end with /bin/romm-launcher, got: {exe}"
        assert "decky-romm-sync" in exe, f"Exe path should contain plugin name, got: {exe}"

    def test_launch_options_format(self, plugin):
        """Launch options must follow the romm:<rom_id> pattern."""
        import re

        pattern = r"^romm:\d+$"

        # Test valid formats
        for rom_id in [1, 42, 4409, 99999]:
            launch_opt = f"romm:{rom_id}"
            assert re.match(pattern, launch_opt), f"Launch option '{launch_opt}' does not match expected pattern"

    def test_start_dir_is_parent_of_exe(self, plugin):
        """Start dir must be the directory containing the launcher."""
        import decky

        exe = os.path.join(decky.DECKY_PLUGIN_DIR, "bin", "romm-launcher")
        start_dir = os.path.join(decky.DECKY_PLUGIN_DIR, "bin")

        assert start_dir == os.path.dirname(exe), f"start_dir ({start_dir}) should be parent of exe ({exe})"

    def test_artwork_id_generation_consistency(self, plugin):
        """Artwork ID must be deterministic for the same exe+name pair."""
        from adapters.steam_config import SteamConfigAdapter

        exe = "/home/deck/homebrew/plugins/decky-romm-sync/bin/romm-launcher"
        name = "Test Game"

        id1 = SteamConfigAdapter.generate_artwork_id(exe, name)
        id2 = SteamConfigAdapter.generate_artwork_id(exe, name)

        assert id1 == id2, "Artwork ID should be deterministic"
        assert isinstance(id1, int), "Artwork ID should be an integer"
        assert id1 > 0, "Artwork ID should be positive (unsigned)"

    def test_artwork_id_differs_per_game(self, plugin):
        """Different game names should produce different artwork IDs."""
        from adapters.steam_config import SteamConfigAdapter

        exe = "/home/deck/homebrew/plugins/decky-romm-sync/bin/romm-launcher"

        id_a = SteamConfigAdapter.generate_artwork_id(exe, "Game A")
        id_b = SteamConfigAdapter.generate_artwork_id(exe, "Game B")

        assert id_a != id_b, "Different games should have different artwork IDs"


class TestPruneOrphanedStagingArtwork:
    def test_removes_staging_not_in_registry(self, plugin, tmp_path):
        """Staging file for a rom_id not in registry should be deleted."""
        grid_dir = tmp_path / "grid"
        grid_dir.mkdir()
        staging = grid_dir / "romm_42_cover.png"
        staging.write_text("fake")

        plugin._steam_config.grid_dir = lambda: str(grid_dir)
        plugin._state["shortcut_registry"] = {}

        plugin._sync_service.prune_orphaned_staging_artwork()
        assert not staging.exists()

    def test_removes_redundant_staging_with_final(self, plugin, tmp_path):
        """Staging file should be removed when final {app_id}p.png exists."""
        grid_dir = tmp_path / "grid"
        grid_dir.mkdir()
        staging = grid_dir / "romm_42_cover.png"
        staging.write_text("fake staging")
        final = grid_dir / "1001p.png"
        final.write_text("fake final")

        plugin._steam_config.grid_dir = lambda: str(grid_dir)
        plugin._state["shortcut_registry"] = {
            "42": {"app_id": 1001, "name": "Game A"},
        }

        plugin._sync_service.prune_orphaned_staging_artwork()
        assert not staging.exists()
        assert final.exists()  # final artwork untouched

    def test_keeps_staging_when_no_final(self, plugin, tmp_path):
        """Staging file kept when rom is in registry but final artwork not yet created."""
        grid_dir = tmp_path / "grid"
        grid_dir.mkdir()
        staging = grid_dir / "romm_42_cover.png"
        staging.write_text("fake staging")

        plugin._steam_config.grid_dir = lambda: str(grid_dir)
        plugin._state["shortcut_registry"] = {
            "42": {"app_id": 1001, "name": "Game A"},
        }

        plugin._sync_service.prune_orphaned_staging_artwork()
        assert staging.exists()

    def test_ignores_non_staging_files(self, plugin, tmp_path):
        """Non-staging files in grid dir should not be touched."""
        grid_dir = tmp_path / "grid"
        grid_dir.mkdir()
        final = grid_dir / "1001p.png"
        final.write_text("final art")
        other = grid_dir / "something_else.png"
        other.write_text("other")

        plugin._steam_config.grid_dir = lambda: str(grid_dir)
        plugin._state["shortcut_registry"] = {}

        plugin._sync_service.prune_orphaned_staging_artwork()
        assert final.exists()
        assert other.exists()

    def test_no_grid_dir_no_crash(self, plugin):
        """When _grid_dir() returns None, pruning should not crash."""
        plugin._steam_config.grid_dir = lambda: None
        plugin._state["shortcut_registry"] = {}

        # Should not raise
        plugin._sync_service.prune_orphaned_staging_artwork()

    def test_handles_os_error(self, plugin, tmp_path, caplog):
        """OSError during os.remove should log warning and not crash."""
        import logging
        from unittest.mock import patch

        grid_dir = tmp_path / "grid"
        grid_dir.mkdir()
        staging = grid_dir / "romm_42_cover.png"
        staging.write_text("fake")

        plugin._steam_config.grid_dir = lambda: str(grid_dir)
        plugin._state["shortcut_registry"] = {}

        with caplog.at_level(logging.WARNING):
            with patch("os.remove", side_effect=OSError("permission denied")):
                plugin._sync_service.prune_orphaned_staging_artwork()

        # File still exists (os.remove was mocked to fail)
        assert staging.exists()
        # Warning should have been logged
        assert any("Failed to remove orphaned staging artwork" in r.message for r in caplog.records)


class TestClassifyRoms:
    """Tests for _classify_roms() delta classification."""

    def _make_sd(
        self,
        rom_id,
        name="Game",
        platform_name="N64",
        platform_slug="n64",
        fs_name="game.z64",
        igdb_id=None,
        sgdb_id=None,
    ):
        """Helper to build a shortcut_data dict matching _fetch_and_prepare output."""
        return {
            "rom_id": rom_id,
            "name": name,
            "platform_name": platform_name,
            "platform_slug": platform_slug,
            "fs_name": fs_name,
            "igdb_id": igdb_id,
            "sgdb_id": sgdb_id,
        }

    def test_all_new_empty_registry(self, plugin):
        """Empty registry -> all in new, none in changed/unchanged."""
        sd = [self._make_sd(1, "Game A"), self._make_sd(2, "Game B")]
        new, changed, unchanged_ids, stale, disabled = plugin._sync_service._classify_roms(sd, {"N64"})
        assert len(new) == 2
        assert changed == []
        assert unchanged_ids == []
        assert stale == []
        assert disabled == 0

    def test_all_unchanged(self, plugin):
        """Registry matches all items -> all in unchanged_ids."""
        plugin._state["shortcut_registry"] = {
            "1": {
                "app_id": 1001,
                "name": "Game A",
                "platform_name": "N64",
                "platform_slug": "n64",
                "fs_name": "gamea.z64",
            },
            "2": {
                "app_id": 1002,
                "name": "Game B",
                "platform_name": "N64",
                "platform_slug": "n64",
                "fs_name": "gameb.z64",
            },
        }
        sd = [
            self._make_sd(1, "Game A", fs_name="gamea.z64"),
            self._make_sd(2, "Game B", fs_name="gameb.z64"),
        ]
        new, changed, unchanged_ids, stale, disabled = plugin._sync_service._classify_roms(sd, {"N64"})
        assert new == []
        assert changed == []
        assert set(unchanged_ids) == {1, 2}
        assert stale == []

    def test_mixed_new_changed_unchanged(self, plugin):
        """Mix of new, changed, unchanged ROMs."""
        plugin._state["shortcut_registry"] = {
            "1": {
                "app_id": 1001,
                "name": "Game A",
                "platform_name": "N64",
                "platform_slug": "n64",
                "fs_name": "gamea.z64",
            },
            "2": {
                "app_id": 1002,
                "name": "Old Name",
                "platform_name": "N64",
                "platform_slug": "n64",
                "fs_name": "gameb.z64",
            },
        }
        sd = [
            self._make_sd(1, "Game A", fs_name="gamea.z64"),  # unchanged
            self._make_sd(2, "New Name", fs_name="gameb.z64"),  # changed (name)
            self._make_sd(3, "Game C", fs_name="gamec.z64"),  # new
        ]
        new, changed, unchanged_ids, stale, disabled = plugin._sync_service._classify_roms(sd, {"N64"})
        assert len(new) == 1
        assert new[0]["rom_id"] == 3
        assert len(changed) == 1
        assert changed[0]["rom_id"] == 2
        assert changed[0]["existing_app_id"] == 1002
        assert unchanged_ids == [1]

    def test_stale_detection(self, plugin):
        """Registry has ROM not in fetched set -> appears in stale."""
        plugin._state["shortcut_registry"] = {
            "1": {"app_id": 1001, "name": "Game A", "platform_name": "N64"},
            "99": {"app_id": 1099, "name": "Deleted Game", "platform_name": "N64"},
        }
        sd = [self._make_sd(1, "Game A", fs_name="")]
        # Must also set fs_name in registry to match
        plugin._state["shortcut_registry"]["1"]["fs_name"] = ""
        plugin._state["shortcut_registry"]["1"]["platform_slug"] = "n64"
        new, changed, unchanged_ids, stale, disabled = plugin._sync_service._classify_roms(sd, {"N64"})
        assert 99 in stale
        assert disabled == 0  # N64 is in fetched_platform_names

    def test_disabled_platform_stale_count(self, plugin):
        """Stale ROMs from platforms not in fetched_platform_names -> counted as disabled."""
        plugin._state["shortcut_registry"] = {
            "1": {"app_id": 1001, "name": "Game A", "platform_name": "SNES"},
        }
        sd = []  # nothing fetched
        new, changed, unchanged_ids, stale, disabled = plugin._sync_service._classify_roms(sd, {"N64"})
        assert 1 in stale
        assert disabled == 1  # SNES is not in {"N64"}

    def test_name_change_detected(self, plugin):
        """ROM name changed -> classified as changed with existing_app_id."""
        plugin._state["shortcut_registry"] = {
            "1": {
                "app_id": 1001,
                "name": "Old Title",
                "platform_name": "N64",
                "platform_slug": "n64",
                "fs_name": "game.z64",
            },
        }
        sd = [self._make_sd(1, "New Title")]
        new, changed, unchanged_ids, stale, disabled = plugin._sync_service._classify_roms(sd, {"N64"})
        assert len(changed) == 1
        assert changed[0]["existing_app_id"] == 1001
        assert new == []
        assert unchanged_ids == []

    def test_platform_name_change_detected(self, plugin):
        """Platform name changed -> classified as changed."""
        plugin._state["shortcut_registry"] = {
            "1": {
                "app_id": 1001,
                "name": "Game A",
                "platform_name": "Nintendo 64",
                "platform_slug": "n64",
                "fs_name": "game.z64",
            },
        }
        sd = [self._make_sd(1, "Game A", platform_name="N64")]
        new, changed, unchanged_ids, stale, disabled = plugin._sync_service._classify_roms(sd, {"N64"})
        assert len(changed) == 1
        assert changed[0]["rom_id"] == 1

    def test_fs_name_change_detected(self, plugin):
        """fs_name changed -> classified as changed."""
        plugin._state["shortcut_registry"] = {
            "1": {
                "app_id": 1001,
                "name": "Game A",
                "platform_name": "N64",
                "platform_slug": "n64",
                "fs_name": "old.z64",
            },
        }
        sd = [self._make_sd(1, "Game A", fs_name="new.z64")]
        new, changed, unchanged_ids, stale, disabled = plugin._sync_service._classify_roms(sd, {"N64"})
        assert len(changed) == 1
        assert changed[0]["rom_id"] == 1

    def test_igdb_id_change_no_false_positive(self, plugin):
        """Only igdb_id/sgdb_id changed -> still unchanged."""
        plugin._state["shortcut_registry"] = {
            "1": {
                "app_id": 1001,
                "name": "Game A",
                "platform_name": "N64",
                "platform_slug": "n64",
                "fs_name": "game.z64",
            },
        }
        sd = [self._make_sd(1, "Game A", igdb_id=999, sgdb_id=888)]
        new, changed, unchanged_ids, stale, disabled = plugin._sync_service._classify_roms(sd, {"N64"})
        assert unchanged_ids == [1]
        assert changed == []
        assert new == []

    def test_registry_without_app_id_is_new(self, plugin):
        """Registry entry without app_id -> classified as new."""
        plugin._state["shortcut_registry"] = {
            "1": {"name": "Game A", "platform_name": "N64"},
        }
        sd = [self._make_sd(1, "Game A")]
        new, changed, unchanged_ids, stale, disabled = plugin._sync_service._classify_roms(sd, {"N64"})
        assert len(new) == 1
        assert new[0]["rom_id"] == 1
        assert changed == []

    def test_first_sync_empty_registry_all_new(self, plugin):
        """First sync (empty registry) -> all new."""
        sd = [self._make_sd(i, f"Game {i}") for i in range(1, 6)]
        new, changed, unchanged_ids, stale, disabled = plugin._sync_service._classify_roms(sd, {"N64"})
        assert len(new) == 5
        assert changed == []
        assert unchanged_ids == []
        assert stale == []
        assert disabled == 0

    def test_no_changes(self, plugin):
        """Exact match -> 0 new, 0 changed, 0 removed."""
        plugin._state["shortcut_registry"] = {
            "1": {
                "app_id": 1001,
                "name": "Game A",
                "platform_name": "N64",
                "platform_slug": "n64",
                "fs_name": "game.z64",
            },
        }
        sd = [self._make_sd(1, "Game A")]
        new, changed, unchanged_ids, stale, disabled = plugin._sync_service._classify_roms(sd, {"N64"})
        assert len(new) == 0
        assert len(changed) == 0
        assert len(stale) == 0
        assert len(unchanged_ids) == 1

    def test_all_stale_disabled_platforms(self, plugin):
        """Everything stale from disabled platforms."""
        plugin._state["shortcut_registry"] = {
            "1": {"app_id": 1001, "name": "Game A", "platform_name": "GBA"},
            "2": {"app_id": 1002, "name": "Game B", "platform_name": "SNES"},
        }
        sd = []  # nothing fetched
        # Neither GBA nor SNES in fetched set
        new, changed, unchanged_ids, stale, disabled = plugin._sync_service._classify_roms(sd, {"N64"})
        assert len(stale) == 2
        assert disabled == 2


class TestSyncPreview:
    """Tests for sync_preview()."""

    @pytest.mark.asyncio
    async def test_returns_correct_summary(self, plugin):
        from unittest.mock import AsyncMock

        import decky

        plugin.loop = asyncio.get_event_loop()
        decky.emit.reset_mock()

        # Mock _fetch_and_prepare to return known data
        platforms = [{"name": "N64", "slug": "n64"}]
        all_roms = [{"id": 1}, {"id": 2}, {"id": 3}]
        shortcuts_data = [
            {"rom_id": 1, "name": "Game A", "platform_name": "N64", "platform_slug": "n64", "fs_name": "a.z64"},
            {"rom_id": 2, "name": "Game B", "platform_name": "N64", "platform_slug": "n64", "fs_name": "b.z64"},
            {"rom_id": 3, "name": "Game C", "platform_name": "N64", "platform_slug": "n64", "fs_name": "c.z64"},
        ]
        plugin._sync_service._fetch_and_prepare = AsyncMock(return_value=(all_roms, shortcuts_data, platforms))
        plugin._sync_service._emit_progress = AsyncMock()

        # Set up registry: rom 1 unchanged, rom 2 changed name
        plugin._state["shortcut_registry"] = {
            "1": {"app_id": 1001, "name": "Game A", "platform_name": "N64", "platform_slug": "n64", "fs_name": "a.z64"},
            "2": {"app_id": 1002, "name": "Old B", "platform_name": "N64", "platform_slug": "n64", "fs_name": "b.z64"},
        }

        result = await plugin.sync_preview()
        assert result["success"] is True
        summary = result["summary"]
        assert summary["new_count"] == 1  # rom 3 is new
        assert summary["changed_count"] == 1  # rom 2 name changed
        assert summary["unchanged_count"] == 1  # rom 1 unchanged
        assert summary["remove_count"] == 0
        assert "preview_id" in result

    @pytest.mark.asyncio
    async def test_populates_pending_delta(self, plugin):
        from unittest.mock import AsyncMock

        import decky

        plugin.loop = asyncio.get_event_loop()
        decky.emit.reset_mock()

        platforms = [{"name": "N64", "slug": "n64"}]
        all_roms = [{"id": 1}]
        shortcuts_data = [
            {"rom_id": 1, "name": "Game A", "platform_name": "N64", "platform_slug": "n64", "fs_name": "a.z64"},
        ]
        plugin._sync_service._fetch_and_prepare = AsyncMock(return_value=(all_roms, shortcuts_data, platforms))
        plugin._sync_service._emit_progress = AsyncMock()

        result = await plugin.sync_preview()
        assert plugin._sync_service._pending_delta is not None
        assert plugin._sync_service._pending_delta["preview_id"] == result["preview_id"]
        assert len(plugin._sync_service._pending_delta["new"]) == 1
        assert plugin._sync_service._pending_delta["platforms_count"] == 1
        assert plugin._sync_service._pending_delta["total_roms"] == 1

    @pytest.mark.asyncio
    async def test_returns_error_when_sync_running(self, plugin):
        plugin._sync_service._sync_state = SyncState.RUNNING
        result = await plugin.sync_preview()
        assert result["success"] is False
        assert "already in progress" in result["message"]

    @pytest.mark.asyncio
    async def test_resets_sync_running_on_completion(self, plugin):
        from unittest.mock import AsyncMock

        import decky

        plugin.loop = asyncio.get_event_loop()
        decky.emit.reset_mock()

        platforms = [{"name": "N64"}]
        all_roms = [{"id": 1}]
        shortcuts_data = [
            {"rom_id": 1, "name": "Game A", "platform_name": "N64", "platform_slug": "n64", "fs_name": "a.z64"},
        ]
        plugin._sync_service._fetch_and_prepare = AsyncMock(return_value=(all_roms, shortcuts_data, platforms))
        plugin._sync_service._emit_progress = AsyncMock()

        await plugin.sync_preview()
        assert plugin._sync_service._sync_state == SyncState.IDLE


class TestSyncApplyDelta:
    """Tests for sync_apply_delta()."""

    def _setup_pending_delta(self, plugin, preview_id="test-preview-123"):
        """Helper to populate _pending_delta with valid data."""
        plugin._sync_service._pending_delta = {
            "preview_id": preview_id,
            "new": [
                {
                    "rom_id": 3,
                    "name": "Game C",
                    "platform_name": "N64",
                    "platform_slug": "n64",
                    "fs_name": "c.z64",
                    "cover_path": "",
                },
            ],
            "changed": [
                {
                    "rom_id": 2,
                    "name": "New B",
                    "existing_app_id": 1002,
                    "platform_name": "N64",
                    "platform_slug": "n64",
                    "fs_name": "b.z64",
                    "cover_path": "",
                },
            ],
            "unchanged_ids": [1],
            "remove_rom_ids": [99],
            "all_shortcuts": {
                1: {"rom_id": 1, "name": "Game A", "platform_name": "N64"},
                2: {"rom_id": 2, "name": "New B", "platform_name": "N64"},
                3: {"rom_id": 3, "name": "Game C", "platform_name": "N64"},
            },
            "platforms_count": 1,
            "total_roms": 3,
        }

    @pytest.mark.asyncio
    async def test_rejects_wrong_preview_id(self, plugin):
        self._setup_pending_delta(plugin, "correct-id")
        result = await plugin.sync_apply_delta("wrong-id")
        assert result["success"] is False
        assert result["error_code"] == "stale_preview"

    @pytest.mark.asyncio
    async def test_rejects_when_no_pending_delta(self, plugin):
        assert plugin._sync_service._pending_delta is None
        result = await plugin.sync_apply_delta("any-id")
        assert result["success"] is False
        assert result["error_code"] == "stale_preview"

    @pytest.mark.asyncio
    async def test_emits_sync_apply_with_delta(self, plugin, tmp_path):
        from unittest.mock import AsyncMock

        import decky

        plugin.loop = asyncio.get_event_loop()
        decky.emit.reset_mock()
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        # Set up registry for unchanged rom
        plugin._state["shortcut_registry"] = {
            "1": {"app_id": 1001, "name": "Game A", "platform_name": "N64"},
        }
        plugin._save_state = lambda: None

        self._setup_pending_delta(plugin)
        plugin._sync_service._emit_progress = AsyncMock()

        result = await plugin.sync_apply_delta("test-preview-123")
        assert result["success"] is True

        # Check decky.emit was called with sync_apply
        emit_calls = [c for c in decky.emit.call_args_list if c[0][0] == "sync_apply"]
        assert len(emit_calls) == 1
        payload = emit_calls[0][0][1]
        assert len(payload["shortcuts"]) == 1  # new
        assert len(payload["changed_shortcuts"]) == 1  # changed
        assert payload["remove_rom_ids"] == [99]

    @pytest.mark.asyncio
    async def test_populates_pending_sync(self, plugin, tmp_path):
        from unittest.mock import AsyncMock

        import decky

        plugin.loop = asyncio.get_event_loop()
        decky.emit.reset_mock()
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._state["shortcut_registry"] = {
            "1": {"app_id": 1001, "name": "Game A", "platform_name": "N64"},
        }
        plugin._save_state = lambda: None

        self._setup_pending_delta(plugin)
        plugin._sync_service._emit_progress = AsyncMock()

        await plugin.sync_apply_delta("test-preview-123")
        assert 1 in plugin._sync_service._pending_sync
        assert 2 in plugin._sync_service._pending_sync
        assert 3 in plugin._sync_service._pending_sync

    @pytest.mark.asyncio
    async def test_clears_pending_delta(self, plugin, tmp_path):
        from unittest.mock import AsyncMock

        import decky

        plugin.loop = asyncio.get_event_loop()
        decky.emit.reset_mock()
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._state["shortcut_registry"] = {
            "1": {"app_id": 1001, "name": "Game A", "platform_name": "N64"},
        }
        plugin._save_state = lambda: None

        self._setup_pending_delta(plugin)
        plugin._sync_service._emit_progress = AsyncMock()

        await plugin.sync_apply_delta("test-preview-123")
        assert plugin._sync_service._pending_delta is None

    @pytest.mark.asyncio
    async def test_builds_collection_map_from_unchanged(self, plugin, tmp_path):
        from unittest.mock import AsyncMock

        import decky

        plugin.loop = asyncio.get_event_loop()
        decky.emit.reset_mock()
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._state["shortcut_registry"] = {
            "1": {"app_id": 1001, "name": "Game A", "platform_name": "N64"},
            "5": {"app_id": 1005, "name": "Game E", "platform_name": "SNES"},
        }
        plugin._save_state = lambda: None

        # Include both rom 1 and 5 as unchanged
        plugin._sync_service._pending_delta = {
            "preview_id": "test-preview-123",
            "new": [],
            "changed": [],
            "unchanged_ids": [1, 5],
            "remove_rom_ids": [],
            "all_shortcuts": {
                1: {"rom_id": 1, "name": "Game A", "platform_name": "N64"},
                5: {"rom_id": 5, "name": "Game E", "platform_name": "SNES"},
            },
            "platforms_count": 2,
            "total_roms": 2,
        }
        plugin._sync_service._emit_progress = AsyncMock()

        await plugin.sync_apply_delta("test-preview-123")

        emit_calls = [c for c in decky.emit.call_args_list if c[0][0] == "sync_apply"]
        assert len(emit_calls) == 1
        collection_map = emit_calls[0][0][1]["collection_platform_app_ids"]
        assert 1001 in collection_map.get("N64", [])
        assert 1005 in collection_map.get("SNES", [])


class TestSyncCancelPreview:
    """Tests for sync_cancel_preview()."""

    @pytest.mark.asyncio
    async def test_clears_pending_delta(self, plugin):
        plugin._sync_service._pending_delta = {
            "preview_id": "some-id",
            "new": [],
            "changed": [],
            "unchanged_ids": [],
            "remove_rom_ids": [],
            "all_shortcuts": {},
            "platforms_count": 0,
            "total_roms": 0,
        }
        result = await plugin.sync_cancel_preview()
        assert plugin._sync_service._pending_delta is None
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_returns_success(self, plugin):
        result = await plugin.sync_cancel_preview()
        assert result == {"success": True}
