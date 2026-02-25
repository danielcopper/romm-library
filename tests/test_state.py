import pytest
import json
import os

# conftest.py patches decky before this import
from main import Plugin


@pytest.fixture
def plugin():
    p = Plugin()
    p.settings = {"romm_url": "", "romm_user": "", "romm_pass": "", "enabled_platforms": {}}
    p._sync_running = False
    p._sync_cancel = False
    p._sync_progress = {"running": False}
    p._state = {"shortcut_registry": {}, "installed_roms": {}, "last_sync": None, "sync_stats": {}}
    p._pending_sync = {}
    p._download_tasks = {}
    p._download_queue = {}
    p._download_in_progress = set()
    p._metadata_cache = {}
    return p


class TestSettings:
    @pytest.mark.asyncio
    async def test_get_settings_masks_password(self, plugin):
        plugin.settings["romm_pass"] = "secret123"
        result = await plugin.get_settings()
        assert result["romm_pass_masked"] == "••••"
        assert "secret123" not in str(result)

    @pytest.mark.asyncio
    async def test_get_settings_empty_password(self, plugin):
        plugin.settings["romm_pass"] = ""
        result = await plugin.get_settings()
        assert result["romm_pass_masked"] == ""

    @pytest.mark.asyncio
    async def test_save_settings_skips_masked_password(self, plugin, tmp_path):
        import decky
        decky.DECKY_PLUGIN_SETTINGS_DIR = str(tmp_path)
        plugin.settings["romm_pass"] = "original"
        await plugin.save_settings("http://example.com", "user", "••••")
        assert plugin.settings["romm_pass"] == "original"

    @pytest.mark.asyncio
    async def test_save_settings_updates_real_password(self, plugin, tmp_path):
        import decky
        decky.DECKY_PLUGIN_SETTINGS_DIR = str(tmp_path)
        plugin.settings["romm_pass"] = "old"
        await plugin.save_settings("http://example.com", "user", "newpass")
        assert plugin.settings["romm_pass"] == "newpass"


class TestLogLevel:
    def test_log_debug_enabled(self, plugin):
        """_log_debug logs when log_level is 'debug'."""
        from unittest.mock import patch
        import decky
        plugin.settings["log_level"] = "debug"
        with patch.object(decky.logger, "info") as mock_info:
            plugin._log_debug("test message")
            mock_info.assert_called_once_with("test message")

    def test_log_debug_disabled_at_warn(self, plugin):
        """_log_debug does not log when log_level is 'warn' (default)."""
        from unittest.mock import patch
        import decky
        plugin.settings["log_level"] = "warn"
        with patch.object(decky.logger, "info") as mock_info:
            plugin._log_debug("test message")
            mock_info.assert_not_called()

    def test_log_debug_disabled_at_info(self, plugin):
        """_log_debug does not log when log_level is 'info'."""
        from unittest.mock import patch
        import decky
        plugin.settings["log_level"] = "info"
        with patch.object(decky.logger, "info") as mock_info:
            plugin._log_debug("test message")
            mock_info.assert_not_called()

    def test_log_debug_disabled_at_error(self, plugin):
        """_log_debug does not log when log_level is 'error'."""
        from unittest.mock import patch
        import decky
        plugin.settings["log_level"] = "error"
        with patch.object(decky.logger, "info") as mock_info:
            plugin._log_debug("test message")
            mock_info.assert_not_called()

    def test_log_debug_missing_setting_defaults_warn(self, plugin):
        """_log_debug does not log when log_level key is missing (defaults to warn)."""
        from unittest.mock import patch
        import decky
        plugin.settings.pop("log_level", None)
        with patch.object(decky.logger, "info") as mock_info:
            plugin._log_debug("test message")
            mock_info.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_log_level_valid(self, plugin, tmp_path):
        import decky
        decky.DECKY_PLUGIN_SETTINGS_DIR = str(tmp_path)
        for level in ("debug", "info", "warn", "error"):
            result = await plugin.save_log_level(level)
            assert result["success"] is True
            assert plugin.settings["log_level"] == level

    @pytest.mark.asyncio
    async def test_save_log_level_invalid(self, plugin, tmp_path):
        import decky
        decky.DECKY_PLUGIN_SETTINGS_DIR = str(tmp_path)
        plugin.settings["log_level"] = "warn"
        result = await plugin.save_log_level("verbose")
        assert result["success"] is False
        assert plugin.settings["log_level"] == "warn"  # unchanged

    @pytest.mark.asyncio
    async def test_get_settings_includes_log_level(self, plugin):
        plugin.settings["log_level"] = "info"
        result = await plugin.get_settings()
        assert result["log_level"] == "info"

    @pytest.mark.asyncio
    async def test_get_settings_defaults_log_level_warn(self, plugin):
        plugin.settings.pop("log_level", None)
        result = await plugin.get_settings()
        assert result["log_level"] == "warn"

    @pytest.mark.asyncio
    async def test_frontend_log_respects_level(self, plugin):
        """frontend_log only logs when message level >= configured level."""
        from unittest.mock import patch
        import decky

        plugin.settings["log_level"] = "warn"
        with patch.object(decky.logger, "info") as mock_info, \
             patch.object(decky.logger, "warning") as mock_warning, \
             patch.object(decky.logger, "error") as mock_error:
            await plugin.frontend_log("debug", "debug msg")
            await plugin.frontend_log("info", "info msg")
            await plugin.frontend_log("warn", "warn msg")
            await plugin.frontend_log("error", "error msg")
            mock_info.assert_not_called()
            mock_warning.assert_called_once_with("[FE] warn msg")
            mock_error.assert_called_once_with("[FE] error msg")

    @pytest.mark.asyncio
    async def test_frontend_log_debug_level_logs_all(self, plugin):
        """With log_level=debug, all levels are logged."""
        from unittest.mock import patch
        import decky

        plugin.settings["log_level"] = "debug"
        with patch.object(decky.logger, "info") as mock_info, \
             patch.object(decky.logger, "warning") as mock_warning, \
             patch.object(decky.logger, "error") as mock_error:
            await plugin.frontend_log("debug", "d")
            await plugin.frontend_log("info", "i")
            await plugin.frontend_log("warn", "w")
            await plugin.frontend_log("error", "e")
            assert mock_info.call_count == 2  # debug + info both use logger.info
            mock_warning.assert_called_once_with("[FE] w")
            mock_error.assert_called_once_with("[FE] e")

    @pytest.mark.asyncio
    async def test_debug_log_backward_compat(self, plugin):
        """debug_log callable delegates to frontend_log('debug', ...)."""
        from unittest.mock import patch
        import decky

        plugin.settings["log_level"] = "debug"
        with patch.object(decky.logger, "info") as mock_info:
            await plugin.debug_log("test backward compat")
            mock_info.assert_called_once_with("[FE] test backward compat")

    def test_migration_debug_logging_true(self, plugin, tmp_path):
        """Old debug_logging=True migrates to log_level='debug'."""
        import decky
        decky.DECKY_PLUGIN_SETTINGS_DIR = str(tmp_path)
        # Write old-format settings
        settings_path = os.path.join(str(tmp_path), "settings.json")
        os.makedirs(str(tmp_path), exist_ok=True)
        with open(settings_path, "w") as f:
            json.dump({"debug_logging": True, "romm_url": ""}, f)
        plugin._load_settings()
        assert "debug_logging" not in plugin.settings
        assert plugin.settings["log_level"] == "debug"

    def test_migration_debug_logging_false(self, plugin, tmp_path):
        """Old debug_logging=False migrates to log_level='warn' (default)."""
        import decky
        decky.DECKY_PLUGIN_SETTINGS_DIR = str(tmp_path)
        settings_path = os.path.join(str(tmp_path), "settings.json")
        os.makedirs(str(tmp_path), exist_ok=True)
        with open(settings_path, "w") as f:
            json.dump({"debug_logging": False, "romm_url": ""}, f)
        plugin._load_settings()
        assert "debug_logging" not in plugin.settings
        assert plugin.settings["log_level"] == "warn"

    @pytest.mark.asyncio
    async def test_sgdb_artwork_silent_when_debug_off(self, plugin, tmp_path):
        """SGDB artwork info calls should not log when log_level is 'warn'."""
        from unittest.mock import patch
        import decky
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin.settings["log_level"] = "warn"
        with patch.object(decky.logger, "info") as mock_info:
            result = await plugin.get_sgdb_artwork_base64(1, 99)
            assert result["base64"] is None
            for call in mock_info.call_args_list:
                assert "SGDB artwork" not in str(call)

    @pytest.mark.asyncio
    async def test_sgdb_artwork_logs_when_debug_enabled(self, plugin, tmp_path):
        """SGDB artwork info calls should log when log_level is 'debug'."""
        from unittest.mock import patch
        import decky
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin.settings["log_level"] = "debug"
        plugin.settings["steamgriddb_api_key"] = ""
        plugin._state["shortcut_registry"]["1"] = {"sgdb_id": None, "igdb_id": None}
        with patch.object(decky.logger, "info") as mock_info:
            result = await plugin.get_sgdb_artwork_base64(1, 1)
            assert result["no_api_key"] is True
            logged_msgs = [str(c) for c in mock_info.call_args_list]
            assert any("SGDB artwork" in m for m in logged_msgs)


class TestPruneStaleState:
    def test_prunes_missing_files(self, plugin, tmp_path):
        import decky
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._state["installed_roms"] = {
            "1": {"rom_id": 1, "file_path": "/nonexistent/game.z64", "system": "n64"},
        }

        plugin._prune_stale_installed_roms()
        assert "1" not in plugin._state["installed_roms"]

    def test_keeps_existing_files(self, plugin, tmp_path):
        import decky
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        rom_file = tmp_path / "game.z64"
        rom_file.write_text("data")

        plugin._state["installed_roms"] = {
            "1": {"rom_id": 1, "file_path": str(rom_file), "system": "n64"},
        }

        plugin._prune_stale_installed_roms()
        assert "1" in plugin._state["installed_roms"]

    def test_keeps_existing_rom_dir(self, plugin, tmp_path):
        import decky
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        rom_dir = tmp_path / "FF7"
        rom_dir.mkdir()

        plugin._state["installed_roms"] = {
            "1": {
                "rom_id": 1,
                "file_path": str(rom_dir / "FF7.m3u"),  # file missing but dir exists
                "rom_dir": str(rom_dir),
                "system": "psx",
            },
        }

        plugin._prune_stale_installed_roms()
        assert "1" in plugin._state["installed_roms"]

    def test_saves_state_only_when_pruned(self, plugin, tmp_path):
        import decky
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        rom_file = tmp_path / "game.z64"
        rom_file.write_text("data")

        plugin._state["installed_roms"] = {
            "1": {"rom_id": 1, "file_path": str(rom_file), "system": "n64"},
        }

        # No pruning needed — state file should NOT be written
        state_path = tmp_path / "state.json"
        plugin._prune_stale_installed_roms()
        assert not state_path.exists()

    def test_prunes_mixed(self, plugin, tmp_path):
        import decky
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        rom_file = tmp_path / "game.z64"
        rom_file.write_text("data")

        plugin._state["installed_roms"] = {
            "1": {"rom_id": 1, "file_path": str(rom_file), "system": "n64"},
            "2": {"rom_id": 2, "file_path": "/gone/game.z64", "system": "snes"},
        }

        plugin._prune_stale_installed_roms()
        assert "1" in plugin._state["installed_roms"]
        assert "2" not in plugin._state["installed_roms"]


class TestPruneStaleStateEdgeCases:
    """Edge case tests for _prune_stale_installed_roms."""

    def test_empty_installed_roms_no_crash(self, plugin, tmp_path):
        import decky
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._state["installed_roms"] = {}
        plugin._prune_stale_installed_roms()
        # Should not crash, _save_state should NOT be called
        state_path = tmp_path / "state.json"
        assert not state_path.exists()

    def test_all_entries_stale(self, plugin, tmp_path):
        import decky
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._state["installed_roms"] = {
            "1": {"rom_id": 1, "file_path": "/gone/a.z64", "system": "n64"},
            "2": {"rom_id": 2, "file_path": "/gone/b.z64", "system": "snes"},
            "3": {"rom_id": 3, "file_path": "/gone/c.z64", "system": "gb"},
        }

        plugin._prune_stale_installed_roms()
        assert plugin._state["installed_roms"] == {}
        # _save_state should have been called (state.json written)
        state_path = tmp_path / "state.json"
        assert state_path.exists()


class TestAtomicSettingsWrite:
    def test_settings_written_atomically(self, plugin, tmp_path):
        import decky
        decky.DECKY_PLUGIN_SETTINGS_DIR = str(tmp_path)

        plugin.settings = {"romm_url": "http://example.com", "romm_user": "user"}
        plugin._save_settings_to_disk()

        settings_path = tmp_path / "settings.json"
        with open(settings_path, "r") as f:
            data = json.load(f)
        assert data["romm_url"] == "http://example.com"
        assert data["romm_user"] == "user"

    def test_settings_no_tmp_left_after_write(self, plugin, tmp_path):
        import decky
        decky.DECKY_PLUGIN_SETTINGS_DIR = str(tmp_path)

        plugin.settings = {"romm_url": "http://example.com"}
        plugin._save_settings_to_disk()

        tmp_file = tmp_path / "settings.json.tmp"
        assert not tmp_file.exists()

    def test_settings_crash_preserves_original(self, plugin, tmp_path):
        from unittest.mock import patch
        import decky
        decky.DECKY_PLUGIN_SETTINGS_DIR = str(tmp_path)

        # Write initial settings
        plugin.settings = {"romm_url": "http://original.com"}
        plugin._save_settings_to_disk()

        # Now simulate a crash during json.dump
        plugin.settings = {"romm_url": "http://corrupted.com"}
        with patch("json.dump", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                plugin._save_settings_to_disk()

        # Original file should still be intact
        settings_path = tmp_path / "settings.json"
        with open(settings_path, "r") as f:
            data = json.load(f)
        assert data["romm_url"] == "http://original.com"


class TestPruneStaleRegistry:
    def test_prunes_missing_app_id(self, plugin, tmp_path):
        import decky
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._state["shortcut_registry"] = {
            "1": {"name": "Game A"},
        }
        plugin._prune_stale_registry()
        assert "1" not in plugin._state["shortcut_registry"]

    def test_prunes_zero_app_id(self, plugin, tmp_path):
        import decky
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._state["shortcut_registry"] = {
            "1": {"app_id": 0, "name": "Game A"},
        }
        plugin._prune_stale_registry()
        assert "1" not in plugin._state["shortcut_registry"]

    def test_prunes_non_int_app_id(self, plugin, tmp_path):
        import decky
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._state["shortcut_registry"] = {
            "1": {"app_id": "abc", "name": "Game A"},
        }
        plugin._prune_stale_registry()
        assert "1" not in plugin._state["shortcut_registry"]

    def test_keeps_valid_entry(self, plugin, tmp_path):
        import decky
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._state["shortcut_registry"] = {
            "1": {"app_id": 12345678, "name": "Game A"},
        }
        plugin._prune_stale_registry()
        assert "1" in plugin._state["shortcut_registry"]

    def test_saves_only_when_pruned(self, plugin, tmp_path):
        import decky
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._state["shortcut_registry"] = {
            "1": {"app_id": 12345678, "name": "Game A"},
        }
        plugin._prune_stale_registry()
        # No pruning needed — state file should NOT be written
        state_path = tmp_path / "state.json"
        assert not state_path.exists()

    def test_empty_registry_no_crash(self, plugin, tmp_path):
        import decky
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._state["shortcut_registry"] = {}
        plugin._prune_stale_registry()
        # Should not crash, state file should NOT be written
        state_path = tmp_path / "state.json"
        assert not state_path.exists()
