import pytest
import json
import os
import asyncio

# conftest.py patches decky before this import
from main import Plugin


@pytest.fixture
def plugin():
    p = Plugin()
    p.settings = {"romm_url": "", "romm_user": "", "romm_pass": "", "enabled_platforms": {}}
    p._sync_running = False
    p._sync_cancel = False
    p._sync_progress = {"running": False}
    p._state = {"shortcut_registry": {}, "installed_roms": {}, "last_sync": None, "sync_stats": {}, "downloaded_bios": {}, "retrodeck_home_path": ""}
    p._pending_sync = {}
    p._download_tasks = {}
    p._download_queue = {}
    p._download_in_progress = set()
    p._metadata_cache = {}
    p._bios_registry = {}
    p._bios_files_index = {}
    return p


class TestPathChangeDetection:
    def test_first_run_stores_path(self, plugin, tmp_path):
        """First run (empty stored path) stores current path, no event."""
        from unittest.mock import patch, MagicMock
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin.loop = MagicMock()

        with patch("lib.retrodeck_config.get_retrodeck_home",
                    return_value="/run/media/deck/SD/retrodeck"):
            plugin._detect_retrodeck_path_change()

        assert plugin._state["retrodeck_home_path"] == "/run/media/deck/SD/retrodeck"
        # No event emitted on first run
        plugin.loop.create_task.assert_not_called()

    def test_no_change_no_notification(self, plugin, tmp_path):
        """Same path as stored — no event, no state change."""
        from unittest.mock import patch, MagicMock
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._state["retrodeck_home_path"] = "/run/media/deck/SD/retrodeck"
        plugin.loop = MagicMock()

        with patch("lib.retrodeck_config.get_retrodeck_home",
                    return_value="/run/media/deck/SD/retrodeck"):
            plugin._detect_retrodeck_path_change()

        plugin.loop.create_task.assert_not_called()

    def test_path_change_emits_event(self, plugin, tmp_path):
        """Path changed — stores both old and new, emits event."""
        from unittest.mock import patch, MagicMock
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        plugin._state["retrodeck_home_path"] = "/home/deck/retrodeck"
        plugin.loop = MagicMock()

        with patch("lib.retrodeck_config.get_retrodeck_home",
                    return_value="/run/media/deck/SD/retrodeck"):
            plugin._detect_retrodeck_path_change()

        assert plugin._state["retrodeck_home_path"] == "/run/media/deck/SD/retrodeck"
        assert plugin._state["retrodeck_home_path_previous"] == "/home/deck/retrodeck"
        plugin.loop.create_task.assert_called_once()

    def test_empty_current_home_no_action(self, plugin, tmp_path):
        """If retrodeck_config returns empty string, do nothing."""
        from unittest.mock import patch, MagicMock
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        plugin.loop = MagicMock()

        with patch("lib.retrodeck_config.get_retrodeck_home", return_value=""):
            plugin._detect_retrodeck_path_change()

        plugin.loop.create_task.assert_not_called()
        assert plugin._state["retrodeck_home_path"] == ""


class TestMigrateRetroDeckFiles:
    @pytest.mark.asyncio
    async def test_no_migration_needed(self, plugin, tmp_path):
        """No previous path — nothing to migrate."""
        import decky
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        result = await plugin.migrate_retrodeck_files()
        assert result["success"] is False
        assert "No path migration needed" in result["message"]

    @pytest.mark.asyncio
    async def test_migrate_roms(self, plugin, tmp_path):
        """Moves ROM files from old to new path, updates state."""
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        old_home = str(tmp_path / "old")
        new_home = str(tmp_path / "new")
        old_rom = os.path.join(old_home, "roms", "n64", "zelda.z64")
        new_rom = os.path.join(new_home, "roms", "n64", "zelda.z64")

        os.makedirs(os.path.dirname(old_rom))
        with open(old_rom, "w") as f:
            f.write("rom data")

        plugin._state["retrodeck_home_path_previous"] = old_home
        plugin._state["retrodeck_home_path"] = new_home
        plugin._state["installed_roms"] = {
            "1": {
                "rom_id": 1,
                "file_path": old_rom,
                "system": "n64",
            }
        }

        result = await plugin.migrate_retrodeck_files()
        assert result["success"] is True
        assert result["roms_moved"] == 1
        assert os.path.exists(new_rom)
        assert not os.path.exists(old_rom)
        assert plugin._state["installed_roms"]["1"]["file_path"] == new_rom

    @pytest.mark.asyncio
    async def test_migrate_bios(self, plugin, tmp_path):
        """Moves tracked BIOS files from old to new path."""
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        old_home = str(tmp_path / "old")
        new_home = str(tmp_path / "new")
        old_bios = os.path.join(old_home, "bios", "scph5501.bin")
        new_bios = os.path.join(new_home, "bios", "scph5501.bin")

        os.makedirs(os.path.dirname(old_bios))
        with open(old_bios, "w") as f:
            f.write("bios data")

        plugin._state["retrodeck_home_path_previous"] = old_home
        plugin._state["retrodeck_home_path"] = new_home
        plugin._state["downloaded_bios"] = {
            "scph5501.bin": {
                "file_path": old_bios,
                "firmware_id": 42,
                "platform_slug": "psx",
            }
        }

        result = await plugin.migrate_retrodeck_files()
        assert result["success"] is True
        assert result["bios_moved"] == 1
        assert os.path.exists(new_bios)
        assert plugin._state["downloaded_bios"]["scph5501.bin"]["file_path"] == new_bios

    @pytest.mark.asyncio
    async def test_migrate_conflicts_need_confirmation(self, plugin, tmp_path):
        """Destination file already exists — first call returns conflicts for user decision."""
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        old_home = str(tmp_path / "old")
        new_home = str(tmp_path / "new")
        old_rom = os.path.join(old_home, "roms", "n64", "zelda.z64")
        new_rom = os.path.join(new_home, "roms", "n64", "zelda.z64")

        os.makedirs(os.path.dirname(old_rom))
        os.makedirs(os.path.dirname(new_rom))
        with open(old_rom, "w") as f:
            f.write("old data")
        with open(new_rom, "w") as f:
            f.write("new data")

        plugin._state["retrodeck_home_path_previous"] = old_home
        plugin._state["retrodeck_home_path"] = new_home
        plugin._state["installed_roms"] = {
            "1": {"rom_id": 1, "file_path": old_rom, "system": "n64"}
        }

        # First call with no strategy returns conflicts
        result = await plugin.migrate_retrodeck_files()
        assert result["needs_confirmation"] is True
        assert result["conflict_count"] == 1
        assert "zelda.z64" in result["conflicts"]
        # Nothing moved yet
        with open(new_rom) as f:
            assert f.read() == "new data"
        with open(old_rom) as f:
            assert f.read() == "old data"

    @pytest.mark.asyncio
    async def test_migrate_conflict_overwrite(self, plugin, tmp_path):
        """Overwrite strategy replaces destination with source."""
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        old_home = str(tmp_path / "old")
        new_home = str(tmp_path / "new")
        old_rom = os.path.join(old_home, "roms", "n64", "zelda.z64")
        new_rom = os.path.join(new_home, "roms", "n64", "zelda.z64")

        os.makedirs(os.path.dirname(old_rom))
        os.makedirs(os.path.dirname(new_rom))
        with open(old_rom, "w") as f:
            f.write("old data")
        with open(new_rom, "w") as f:
            f.write("new data")

        plugin._state["retrodeck_home_path_previous"] = old_home
        plugin._state["retrodeck_home_path"] = new_home
        plugin._state["installed_roms"] = {
            "1": {"rom_id": 1, "file_path": old_rom, "system": "n64"}
        }

        result = await plugin.migrate_retrodeck_files("overwrite")
        assert result["success"] is True
        assert result["roms_moved"] == 1
        with open(new_rom) as f:
            assert f.read() == "old data"
        assert plugin._state["installed_roms"]["1"]["file_path"] == new_rom

    @pytest.mark.asyncio
    async def test_migrate_conflict_skip(self, plugin, tmp_path):
        """Skip strategy keeps destination file, updates state path."""
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        old_home = str(tmp_path / "old")
        new_home = str(tmp_path / "new")
        old_rom = os.path.join(old_home, "roms", "n64", "zelda.z64")
        new_rom = os.path.join(new_home, "roms", "n64", "zelda.z64")

        os.makedirs(os.path.dirname(old_rom))
        os.makedirs(os.path.dirname(new_rom))
        with open(old_rom, "w") as f:
            f.write("old data")
        with open(new_rom, "w") as f:
            f.write("new data")

        plugin._state["retrodeck_home_path_previous"] = old_home
        plugin._state["retrodeck_home_path"] = new_home
        plugin._state["installed_roms"] = {
            "1": {"rom_id": 1, "file_path": old_rom, "system": "n64"}
        }

        result = await plugin.migrate_retrodeck_files("skip")
        assert result["success"] is True
        assert result["roms_moved"] == 1
        # Destination file preserved
        with open(new_rom) as f:
            assert f.read() == "new data"
        # State updated to new path
        assert plugin._state["installed_roms"]["1"]["file_path"] == new_rom

    @pytest.mark.asyncio
    async def test_migrate_source_missing(self, plugin, tmp_path):
        """Source file gone — skip silently."""
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        old_home = str(tmp_path / "old")
        new_home = str(tmp_path / "new")

        plugin._state["retrodeck_home_path_previous"] = old_home
        plugin._state["retrodeck_home_path"] = new_home
        plugin._state["installed_roms"] = {
            "1": {"rom_id": 1, "file_path": os.path.join(old_home, "roms", "n64", "gone.z64"), "system": "n64"}
        }

        result = await plugin.migrate_retrodeck_files()
        assert result["roms_moved"] == 0
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_migrate_creates_subdirs(self, plugin, tmp_path):
        """Target subdirectories are created as needed."""
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        old_home = str(tmp_path / "old")
        new_home = str(tmp_path / "new")
        old_bios = os.path.join(old_home, "bios", "dc", "dc_boot.bin")

        os.makedirs(os.path.dirname(old_bios))
        with open(old_bios, "w") as f:
            f.write("bios")

        plugin._state["retrodeck_home_path_previous"] = old_home
        plugin._state["retrodeck_home_path"] = new_home
        plugin._state["downloaded_bios"] = {
            "dc_boot.bin": {
                "file_path": old_bios,
                "firmware_id": 7,
                "platform_slug": "dc",
            }
        }

        result = await plugin.migrate_retrodeck_files()
        assert result["bios_moved"] == 1
        new_bios = os.path.join(new_home, "bios", "dc", "dc_boot.bin")
        assert os.path.exists(new_bios)

    @pytest.mark.asyncio
    async def test_clears_previous_on_success(self, plugin, tmp_path):
        """After successful migration, retrodeck_home_path_previous is cleared."""
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        old_home = str(tmp_path / "old")
        new_home = str(tmp_path / "new")

        plugin._state["retrodeck_home_path_previous"] = old_home
        plugin._state["retrodeck_home_path"] = new_home
        # No files to move — success with 0 moved

        result = await plugin.migrate_retrodeck_files()
        assert result["success"] is True
        assert "retrodeck_home_path_previous" not in plugin._state
