import pytest
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
    p._state = {"shortcut_registry": {}, "installed_roms": {}, "last_sync": None, "sync_stats": {}}
    p._pending_sync = {}
    p._download_tasks = {}
    p._download_queue = {}
    p._download_in_progress = set()
    p._metadata_cache = {}
    p._bios_registry = {}
    return p


class TestFirmwareDestPath:
    """Tests for _firmware_dest_path — BIOS destination mapping."""

    def test_flat_default(self, plugin, tmp_path):
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        fw = {"file_name": "bios.bin", "file_path": "bios/n64/bios.bin"}
        dest = plugin._firmware_dest_path(fw)
        assert dest == os.path.join(str(tmp_path), "retrodeck", "bios", "bios.bin")

    def test_dreamcast_subfolder(self, plugin, tmp_path):
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        fw = {"file_name": "dc_boot.bin", "file_path": "bios/dc/dc_boot.bin"}
        dest = plugin._firmware_dest_path(fw)
        assert dest == os.path.join(str(tmp_path), "retrodeck", "bios", "dc", "dc_boot.bin")

    def test_ps2_subfolder(self, plugin, tmp_path):
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        fw = {"file_name": "scph10000.bin", "file_path": "bios/ps2/scph10000.bin"}
        dest = plugin._firmware_dest_path(fw)
        assert dest == os.path.join(str(tmp_path), "retrodeck", "bios", "pcsx2", "bios", "scph10000.bin")

    def test_unknown_platform_flat(self, plugin, tmp_path):
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        fw = {"file_name": "fw.bin", "file_path": "bios/saturn/fw.bin"}
        dest = plugin._firmware_dest_path(fw)
        assert dest == os.path.join(str(tmp_path), "retrodeck", "bios", "fw.bin")


class TestGetFirmwareStatus:
    @pytest.mark.asyncio
    async def test_returns_grouped_platforms(self, plugin, tmp_path):
        from unittest.mock import AsyncMock, MagicMock
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        firmware_list = [
            {"id": 1, "file_name": "bios_dc.bin", "file_path": "bios/dc/bios_dc.bin", "file_size_bytes": 2048, "md5_hash": "abc123"},
            {"id": 2, "file_name": "flash_dc.bin", "file_path": "bios/dc/flash_dc.bin", "file_size_bytes": 1024, "md5_hash": "def456"},
            {"id": 3, "file_name": "scph.bin", "file_path": "bios/ps2/scph.bin", "file_size_bytes": 4096, "md5_hash": ""},
        ]

        plugin.loop = MagicMock()
        plugin.loop.run_in_executor = AsyncMock(return_value=firmware_list)

        result = await plugin.get_firmware_status()
        assert result["success"] is True
        assert len(result["platforms"]) == 2

        dc_plat = next(p for p in result["platforms"] if p["platform_slug"] == "dc")
        assert len(dc_plat["files"]) == 2
        assert all(not f["downloaded"] for f in dc_plat["files"])

    @pytest.mark.asyncio
    async def test_detects_downloaded_files(self, plugin, tmp_path):
        from unittest.mock import AsyncMock, MagicMock
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        bios_dir = tmp_path / "retrodeck" / "bios" / "dc"
        bios_dir.mkdir(parents=True)
        (bios_dir / "bios_dc.bin").write_bytes(b"\x00" * 100)

        firmware_list = [
            {"id": 1, "file_name": "bios_dc.bin", "file_path": "bios/dc/bios_dc.bin", "file_size_bytes": 100, "md5_hash": ""},
        ]

        plugin.loop = MagicMock()
        plugin.loop.run_in_executor = AsyncMock(return_value=firmware_list)

        result = await plugin.get_firmware_status()
        assert result["success"] is True
        assert result["platforms"][0]["files"][0]["downloaded"] is True

    @pytest.mark.asyncio
    async def test_handles_api_error(self, plugin):
        from unittest.mock import AsyncMock, MagicMock

        plugin.loop = MagicMock()
        plugin.loop.run_in_executor = AsyncMock(side_effect=Exception("404 Not Found"))

        result = await plugin.get_firmware_status()
        assert result["success"] is False
        assert "Failed" in result["message"]


class TestDownloadFirmware:
    @pytest.mark.asyncio
    async def test_downloads_and_verifies_md5(self, plugin, tmp_path):
        from unittest.mock import AsyncMock, MagicMock, patch
        import hashlib
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        content = b"firmware data here"
        expected_md5 = hashlib.md5(content).hexdigest()

        fw_detail = {
            "id": 10,
            "file_name": "bios.bin",
            "file_path": "bios/n64/bios.bin",
            "file_size_bytes": len(content),
            "md5_hash": expected_md5,
        }

        def fake_download(path, dest, progress_callback=None):
            with open(dest, "wb") as f:
                f.write(content)

        plugin.loop = asyncio.get_event_loop()

        with patch.object(plugin, "_romm_request", return_value=fw_detail), \
             patch.object(plugin, "_romm_download", side_effect=fake_download):
            result = await plugin.download_firmware(10)

        assert result["success"] is True
        assert result["md5_match"] is True
        assert os.path.exists(result["file_path"])

    @pytest.mark.asyncio
    async def test_handles_download_error(self, plugin, tmp_path):
        from unittest.mock import AsyncMock, MagicMock, patch
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        fw_detail = {
            "id": 10,
            "file_name": "bios.bin",
            "file_path": "bios/n64/bios.bin",
            "file_size_bytes": 100,
            "md5_hash": "",
        }

        plugin.loop = asyncio.get_event_loop()

        with patch.object(plugin, "_romm_request", return_value=fw_detail), \
             patch.object(plugin, "_romm_download", side_effect=IOError("Connection reset")):
            result = await plugin.download_firmware(10)

        assert result["success"] is False
        assert "Download failed" in result["message"]


class TestDownloadAllFirmware:
    @pytest.mark.asyncio
    async def test_downloads_missing_only(self, plugin, tmp_path):
        from unittest.mock import AsyncMock, MagicMock, patch
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        # Pre-create one file so it's skipped
        bios_dir = tmp_path / "retrodeck" / "bios" / "dc"
        bios_dir.mkdir(parents=True)
        (bios_dir / "existing.bin").write_bytes(b"\x00" * 50)

        firmware_list = [
            {"id": 1, "file_name": "existing.bin", "file_path": "bios/dc/existing.bin", "file_size_bytes": 50, "md5_hash": ""},
            {"id": 2, "file_name": "missing.bin", "file_path": "bios/dc/missing.bin", "file_size_bytes": 100, "md5_hash": ""},
        ]

        plugin.loop = asyncio.get_event_loop()

        download_called_ids = []

        async def fake_download_firmware(fw_id):
            download_called_ids.append(fw_id)
            return {"success": True}

        with patch.object(plugin, "_romm_request", return_value=firmware_list), \
             patch.object(plugin, "download_firmware", side_effect=fake_download_firmware):
            result = await plugin.download_all_firmware("dc")

        assert result["success"] is True
        assert result["downloaded"] == 1
        assert 2 in download_called_ids
        assert 1 not in download_called_ids


class TestDeletePlatformBios:
    @pytest.mark.asyncio
    async def test_delete_platform_bios_happy_path(self, plugin, tmp_path):
        """Deleting platform BIOS removes downloaded files."""
        from unittest.mock import AsyncMock
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        bios_dir = tmp_path / "retrodeck" / "bios"
        bios_dir.mkdir(parents=True)
        bios_file = bios_dir / "scph5501.bin"
        bios_file.write_bytes(b"\x00" * 512)

        # Mock check_platform_bios to return our test file
        async def mock_check(slug):
            return {
                "needs_bios": True,
                "server_count": 1,
                "local_count": 1,
                "all_downloaded": True,
                "files": [{"file_name": "scph5501.bin", "downloaded": True, "local_path": str(bios_file)}],
            }
        plugin.check_platform_bios = mock_check

        result = await plugin.delete_platform_bios("psx")
        assert result["success"] is True
        assert result["deleted_count"] == 1
        assert not bios_file.exists()

    @pytest.mark.asyncio
    async def test_delete_platform_bios_no_files(self, plugin):
        """Deleting BIOS when none exist returns success with 0."""
        async def mock_check(slug):
            return {"needs_bios": False}
        plugin.check_platform_bios = mock_check

        result = await plugin.delete_platform_bios("snes")
        assert result["success"] is True
        assert result["deleted_count"] == 0

    @pytest.mark.asyncio
    async def test_delete_platform_bios_skips_not_downloaded(self, plugin, tmp_path):
        """Only files with downloaded=True are deleted."""
        from unittest.mock import AsyncMock
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        async def mock_check(slug):
            return {
                "needs_bios": True,
                "server_count": 2,
                "local_count": 0,
                "all_downloaded": False,
                "files": [
                    {"file_name": "bios1.bin", "downloaded": False, "local_path": "/fake/path1"},
                    {"file_name": "bios2.bin", "downloaded": False, "local_path": "/fake/path2"},
                ],
            }
        plugin.check_platform_bios = mock_check

        result = await plugin.delete_platform_bios("psx")
        assert result["success"] is True
        assert result["deleted_count"] == 0


class TestBiosRegistry:
    def test_load_bios_registry(self, plugin, tmp_path):
        """Loads registry JSON and verifies structure."""
        import json

        registry_data = {
            "_meta": {"version": "1.0", "description": "Test registry"},
            "files": {
                "bios.bin": {
                    "description": "Main BIOS",
                    "required": True,
                    "md5": "abc123",
                    "sha1": "def456",
                    "size": 2048,
                },
                "optional.bin": {
                    "description": "Optional firmware",
                    "required": False,
                    "md5": "789abc",
                    "sha1": "012def",
                    "size": 1024,
                },
            },
        }

        defaults_dir = tmp_path / "defaults"
        defaults_dir.mkdir()
        registry_file = defaults_dir / "bios_registry.json"
        registry_file.write_text(json.dumps(registry_data))

        from unittest.mock import patch
        # _load_bios_registry uses __file__ to locate bios_registry.json relative to lib/
        # We patch os.path.dirname to redirect to our tmp_path
        fake_lib_dir = str(tmp_path / "lib")
        with patch("lib.firmware.os.path.dirname", side_effect=[fake_lib_dir, str(tmp_path)]):
            plugin._load_bios_registry()

        assert "_meta" in plugin._bios_registry
        assert "files" in plugin._bios_registry
        assert "bios.bin" in plugin._bios_registry["files"]
        assert plugin._bios_registry["files"]["bios.bin"]["required"] is True
        assert plugin._bios_registry["files"]["optional.bin"]["required"] is False

    def test_load_bios_registry_missing_file(self, plugin):
        """When registry file doesn't exist, returns empty dict."""
        from unittest.mock import patch

        with patch("lib.firmware.os.path.dirname", side_effect=["/nonexistent/lib", "/nonexistent"]):
            plugin._load_bios_registry()

        assert plugin._bios_registry == {}

    def test_enrich_firmware_required(self, plugin):
        """File in registry marked required=True."""
        plugin._bios_registry = {
            "files": {
                "scph5501.bin": {
                    "description": "PS1 BIOS (USA)",
                    "required": True,
                    "md5": "abc123",
                },
            },
        }
        file_dict = {"file_name": "scph5501.bin", "md5": ""}
        result = plugin._enrich_firmware_file(file_dict)
        assert result["required"] is True
        assert result["description"] == "PS1 BIOS (USA)"

    def test_enrich_firmware_optional(self, plugin):
        """File in registry marked required=False."""
        plugin._bios_registry = {
            "files": {
                "optional_fw.bin": {
                    "description": "Optional debug firmware",
                    "required": False,
                    "md5": "",
                },
            },
        }
        file_dict = {"file_name": "optional_fw.bin", "md5": ""}
        result = plugin._enrich_firmware_file(file_dict)
        assert result["required"] is False
        assert result["description"] == "Optional debug firmware"

    def test_enrich_firmware_unknown_defaults_required(self, plugin):
        """File NOT in registry defaults to required=True."""
        plugin._bios_registry = {"files": {}}
        file_dict = {"file_name": "unknown_bios.bin", "md5": ""}
        result = plugin._enrich_firmware_file(file_dict)
        assert result["required"] is True
        assert result["description"] == "unknown_bios.bin"

    def test_hash_validation_match(self, plugin):
        """RomM md5 matches registry md5."""
        plugin._bios_registry = {
            "files": {
                "bios.bin": {
                    "description": "Test BIOS",
                    "required": True,
                    "md5": "abc123def456",
                },
            },
        }
        file_dict = {"file_name": "bios.bin", "md5": "abc123def456"}
        result = plugin._enrich_firmware_file(file_dict)
        assert result["hash_valid"] is True

    def test_hash_validation_mismatch(self, plugin):
        """RomM md5 differs from registry md5."""
        plugin._bios_registry = {
            "files": {
                "bios.bin": {
                    "description": "Test BIOS",
                    "required": True,
                    "md5": "abc123def456",
                },
            },
        }
        file_dict = {"file_name": "bios.bin", "md5": "000000000000"}
        result = plugin._enrich_firmware_file(file_dict)
        assert result["hash_valid"] is False

    def test_hash_validation_null(self, plugin):
        """No hash from either source results in hash_valid=None."""
        plugin._bios_registry = {
            "files": {
                "bios.bin": {
                    "description": "Test BIOS",
                    "required": True,
                    "md5": "",
                },
            },
        }
        file_dict = {"file_name": "bios.bin", "md5": ""}
        result = plugin._enrich_firmware_file(file_dict)
        assert result["hash_valid"] is None

    def test_hash_validation_null_no_registry_entry(self, plugin):
        """File not in registry and no RomM hash -> hash_valid=None."""
        plugin._bios_registry = {"files": {}}
        file_dict = {"file_name": "bios.bin", "md5": ""}
        result = plugin._enrich_firmware_file(file_dict)
        assert result["hash_valid"] is None

    def test_hash_validation_case_insensitive(self, plugin):
        """Hash comparison is case-insensitive."""
        plugin._bios_registry = {
            "files": {
                "bios.bin": {
                    "description": "Test BIOS",
                    "required": True,
                    "md5": "ABC123DEF456",
                },
            },
        }
        file_dict = {"file_name": "bios.bin", "md5": "abc123def456"}
        result = plugin._enrich_firmware_file(file_dict)
        assert result["hash_valid"] is True


class TestCheckPlatformBiosRequired:
    @pytest.mark.asyncio
    async def test_required_counts(self, plugin, tmp_path):
        """check_platform_bios includes required_count/required_downloaded."""
        from unittest.mock import AsyncMock, MagicMock
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        firmware_list = [
            {"id": 1, "file_name": "required1.bin", "file_path": "bios/dc/required1.bin", "file_size_bytes": 100, "md5_hash": ""},
            {"id": 2, "file_name": "required2.bin", "file_path": "bios/dc/required2.bin", "file_size_bytes": 200, "md5_hash": ""},
            {"id": 3, "file_name": "optional1.bin", "file_path": "bios/dc/optional1.bin", "file_size_bytes": 300, "md5_hash": ""},
        ]

        plugin._bios_registry = {
            "files": {
                "required1.bin": {"description": "Required BIOS 1", "required": True, "md5": ""},
                "required2.bin": {"description": "Required BIOS 2", "required": True, "md5": ""},
                "optional1.bin": {"description": "Optional firmware", "required": False, "md5": ""},
            },
        }

        plugin.loop = MagicMock()
        plugin.loop.run_in_executor = AsyncMock(return_value=firmware_list)

        result = await plugin.check_platform_bios("dc")
        assert result["needs_bios"] is True
        assert result["required_count"] == 2
        assert result["required_downloaded"] == 0
        assert result["server_count"] == 3

    @pytest.mark.asyncio
    async def test_all_required_downloaded(self, plugin, tmp_path):
        """When all required files are downloaded, counts reflect this."""
        from unittest.mock import AsyncMock, MagicMock
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        # Create downloaded required files
        bios_dir = tmp_path / "retrodeck" / "bios" / "dc"
        bios_dir.mkdir(parents=True)
        (bios_dir / "required1.bin").write_bytes(b"\x00" * 100)
        (bios_dir / "required2.bin").write_bytes(b"\x00" * 200)
        # Leave optional1.bin not downloaded

        firmware_list = [
            {"id": 1, "file_name": "required1.bin", "file_path": "bios/dc/required1.bin", "file_size_bytes": 100, "md5_hash": ""},
            {"id": 2, "file_name": "required2.bin", "file_path": "bios/dc/required2.bin", "file_size_bytes": 200, "md5_hash": ""},
            {"id": 3, "file_name": "optional1.bin", "file_path": "bios/dc/optional1.bin", "file_size_bytes": 300, "md5_hash": ""},
        ]

        plugin._bios_registry = {
            "files": {
                "required1.bin": {"description": "Required BIOS 1", "required": True, "md5": ""},
                "required2.bin": {"description": "Required BIOS 2", "required": True, "md5": ""},
                "optional1.bin": {"description": "Optional firmware", "required": False, "md5": ""},
            },
        }

        plugin.loop = MagicMock()
        plugin.loop.run_in_executor = AsyncMock(return_value=firmware_list)

        result = await plugin.check_platform_bios("dc")
        assert result["needs_bios"] is True
        assert result["required_count"] == 2
        assert result["required_downloaded"] == 2
        assert result["local_count"] == 2
        # all_downloaded is False because optional1.bin is not downloaded
        assert result["all_downloaded"] is False

    @pytest.mark.asyncio
    async def test_per_file_required_and_description(self, plugin, tmp_path):
        """Individual files include required and description from registry."""
        from unittest.mock import AsyncMock, MagicMock
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        firmware_list = [
            {"id": 1, "file_name": "bios.bin", "file_path": "bios/dc/bios.bin", "file_size_bytes": 100, "md5_hash": ""},
        ]

        plugin._bios_registry = {
            "files": {
                "bios.bin": {"description": "Dreamcast BIOS", "required": True, "md5": ""},
            },
        }

        plugin.loop = MagicMock()
        plugin.loop.run_in_executor = AsyncMock(return_value=firmware_list)

        result = await plugin.check_platform_bios("dc")
        assert result["files"][0]["required"] is True
        assert result["files"][0]["description"] == "Dreamcast BIOS"


class TestDownloadRequiredFirmware:
    @pytest.mark.asyncio
    async def test_downloads_required_only(self, plugin, tmp_path):
        """Only downloads files marked required, skips optional."""
        from unittest.mock import AsyncMock, MagicMock, patch
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        firmware_list = [
            {"id": 1, "file_name": "required.bin", "file_path": "bios/dc/required.bin", "file_size_bytes": 100, "md5_hash": ""},
            {"id": 2, "file_name": "optional.bin", "file_path": "bios/dc/optional.bin", "file_size_bytes": 200, "md5_hash": ""},
        ]

        plugin._bios_registry = {
            "files": {
                "required.bin": {"description": "Required BIOS", "required": True, "md5": ""},
                "optional.bin": {"description": "Optional firmware", "required": False, "md5": ""},
            },
        }

        plugin.loop = asyncio.get_event_loop()

        download_called_ids = []

        async def fake_download_firmware(fw_id):
            download_called_ids.append(fw_id)
            return {"success": True}

        with patch.object(plugin, "_romm_request", return_value=firmware_list), \
             patch.object(plugin, "download_firmware", side_effect=fake_download_firmware):
            result = await plugin.download_required_firmware("dc")

        assert result["success"] is True
        assert result["downloaded"] == 1
        assert 1 in download_called_ids
        assert 2 not in download_called_ids

    @pytest.mark.asyncio
    async def test_skips_already_downloaded_required(self, plugin, tmp_path):
        """Skips required files that are already downloaded."""
        from unittest.mock import AsyncMock, MagicMock, patch
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        # Pre-create one required file so it's skipped
        bios_dir = tmp_path / "retrodeck" / "bios" / "dc"
        bios_dir.mkdir(parents=True)
        (bios_dir / "existing.bin").write_bytes(b"\x00" * 100)

        firmware_list = [
            {"id": 1, "file_name": "existing.bin", "file_path": "bios/dc/existing.bin", "file_size_bytes": 100, "md5_hash": ""},
            {"id": 2, "file_name": "missing.bin", "file_path": "bios/dc/missing.bin", "file_size_bytes": 200, "md5_hash": ""},
        ]

        plugin._bios_registry = {
            "files": {
                "existing.bin": {"description": "Already downloaded", "required": True, "md5": ""},
                "missing.bin": {"description": "Not yet downloaded", "required": True, "md5": ""},
            },
        }

        plugin.loop = asyncio.get_event_loop()

        download_called_ids = []

        async def fake_download_firmware(fw_id):
            download_called_ids.append(fw_id)
            return {"success": True}

        with patch.object(plugin, "_romm_request", return_value=firmware_list), \
             patch.object(plugin, "download_firmware", side_effect=fake_download_firmware):
            result = await plugin.download_required_firmware("dc")

        assert result["success"] is True
        assert result["downloaded"] == 1
        assert 2 in download_called_ids
        assert 1 not in download_called_ids
