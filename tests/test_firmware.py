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
    p._state = {"shortcut_registry": {}, "installed_roms": {}, "last_sync": None, "sync_stats": {}, "downloaded_bios": {}, "retrodeck_home_path": ""}
    p._pending_sync = {}
    p._download_tasks = {}
    p._download_queue = {}
    p._download_in_progress = set()
    p._metadata_cache = {}
    p._bios_registry = {}
    p._bios_files_index = {}
    return p


class TestFirmwareDestPath:
    """Tests for _firmware_dest_path — registry-based BIOS destination mapping."""

    def test_flat_default_no_registry(self, plugin, tmp_path):
        """File not in registry goes flat in bios root."""
        from unittest.mock import patch
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        with patch("lib.retrodeck_config.get_bios_path",
                    return_value=os.path.join(str(tmp_path), "retrodeck", "bios")):
            fw = {"file_name": "bios.bin", "file_path": "bios/n64/bios.bin"}
            dest = plugin._firmware_dest_path(fw)
            assert dest == os.path.join(str(tmp_path), "retrodeck", "bios", "bios.bin")

    def test_dreamcast_subfolder_from_registry(self, plugin, tmp_path):
        """Registry firmware_path with subdirectory places file correctly."""
        from unittest.mock import patch
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        plugin._bios_files_index["dc_boot.bin"] = {
            "description": "Dreamcast BIOS",
            "required": True,
            "firmware_path": "dc/dc_boot.bin",
            "platform": "dc",
        }

        with patch("lib.retrodeck_config.get_bios_path",
                    return_value=os.path.join(str(tmp_path), "retrodeck", "bios")):
            fw = {"file_name": "dc_boot.bin", "file_path": "bios/dc/dc_boot.bin"}
            dest = plugin._firmware_dest_path(fw)
            assert dest == os.path.join(str(tmp_path), "retrodeck", "bios", "dc", "dc_boot.bin")

    def test_psx_flat_from_registry(self, plugin, tmp_path):
        """Registry firmware_path without subdirectory goes flat."""
        from unittest.mock import patch
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        plugin._bios_files_index["scph5501.bin"] = {
            "description": "PS1 US BIOS",
            "required": True,
            "firmware_path": "scph5501.bin",
            "platform": "psx",
        }

        with patch("lib.retrodeck_config.get_bios_path",
                    return_value=os.path.join(str(tmp_path), "retrodeck", "bios")):
            fw = {"file_name": "scph5501.bin", "file_path": "bios/ps/scph5501.bin"}
            dest = plugin._firmware_dest_path(fw)
            assert dest == os.path.join(str(tmp_path), "retrodeck", "bios", "scph5501.bin")

    def test_uses_dynamic_bios_path(self, plugin, tmp_path):
        """Uses retrodeck_config.get_bios_path() for the base directory."""
        from unittest.mock import patch

        sd_bios = "/run/media/deck/Emulation/retrodeck/bios"
        with patch("lib.retrodeck_config.get_bios_path", return_value=sd_bios):
            fw = {"file_name": "fw.bin", "file_path": "bios/saturn/fw.bin"}
            dest = plugin._firmware_dest_path(fw)
            assert dest == os.path.join(sd_bios, "fw.bin")

    def test_unknown_file_flat_fallback(self, plugin, tmp_path):
        """File not in registry falls back to flat in bios root."""
        from unittest.mock import patch
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        with patch("lib.retrodeck_config.get_bios_path",
                    return_value=os.path.join(str(tmp_path), "retrodeck", "bios")):
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

        # File goes flat in bios root (not in registry, no firmware_path)
        bios_dir = tmp_path / "retrodeck" / "bios"
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
    async def test_handles_api_error_with_offline_fallback(self, plugin):
        from unittest.mock import AsyncMock, MagicMock

        plugin.loop = MagicMock()
        plugin.loop.run_in_executor = AsyncMock(side_effect=Exception("Connection refused"))

        result = await plugin.get_firmware_status()
        assert result["success"] is True
        assert result["server_offline"] is True
        assert "platforms" in result


class TestDownloadFirmware:
    @pytest.mark.asyncio
    async def test_downloads_and_verifies_md5(self, plugin, tmp_path):
        from unittest.mock import AsyncMock, MagicMock, patch
        import hashlib
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

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
        # Verify state tracking
        assert "bios.bin" in plugin._state["downloaded_bios"]
        assert plugin._state["downloaded_bios"]["bios.bin"]["firmware_id"] == 10

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

        # Pre-create one file so it's skipped (flat in bios root, not in registry)
        bios_dir = tmp_path / "retrodeck" / "bios"
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
        """Deleting platform BIOS removes downloaded files and state entries."""
        from unittest.mock import AsyncMock
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path)

        bios_dir = tmp_path / "retrodeck" / "bios"
        bios_dir.mkdir(parents=True)
        bios_file = bios_dir / "scph5501.bin"
        bios_file.write_bytes(b"\x00" * 512)

        # Pre-populate state tracking
        plugin._state["downloaded_bios"]["scph5501.bin"] = {
            "file_path": str(bios_file),
            "firmware_id": 42,
            "platform_slug": "psx",
        }

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
        # Verify state entry removed
        assert "scph5501.bin" not in plugin._state["downloaded_bios"]

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
        """Loads registry JSON and verifies structure + _bios_files_index."""
        import json

        registry_data = {
            "_meta": {"version": "2.0.0", "description": "Test registry"},
            "platforms": {
                "psx": {
                    "bios.bin": {
                        "description": "Main BIOS",
                        "required": True,
                        "md5": "abc123",
                        "sha1": "def456",
                        "size": 2048,
                    },
                },
                "dc": {
                    "optional.bin": {
                        "description": "Optional firmware",
                        "required": False,
                        "md5": "789abc",
                        "sha1": "012def",
                        "size": 1024,
                    },
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
        assert "platforms" in plugin._bios_registry
        assert "psx" in plugin._bios_registry["platforms"]
        assert "bios.bin" in plugin._bios_registry["platforms"]["psx"]
        assert plugin._bios_registry["platforms"]["psx"]["bios.bin"]["required"] is True
        assert "dc" in plugin._bios_registry["platforms"]
        assert plugin._bios_registry["platforms"]["dc"]["optional.bin"]["required"] is False
        # Verify _bios_files_index is populated
        assert "bios.bin" in plugin._bios_files_index
        assert plugin._bios_files_index["bios.bin"]["platform"] == "psx"
        assert "optional.bin" in plugin._bios_files_index
        assert plugin._bios_files_index["optional.bin"]["platform"] == "dc"

    def test_load_bios_registry_missing_file(self, plugin):
        """When registry file doesn't exist, returns empty dict."""
        from unittest.mock import patch

        with patch("lib.firmware.os.path.dirname", side_effect=["/nonexistent/lib", "/nonexistent"]):
            plugin._load_bios_registry()

        assert plugin._bios_registry == {}

    def test_enrich_firmware_required(self, plugin):
        """File in registry marked required=True."""
        plugin._bios_registry = {
            "platforms": {
                "psx": {
                    "scph5501.bin": {
                        "description": "PS1 BIOS (USA)",
                        "required": True,
                        "md5": "abc123",
                    },
                },
            },
        }
        plugin._bios_files_index = {
            "scph5501.bin": {
                "description": "PS1 BIOS (USA)",
                "required": True,
                "md5": "abc123",
                "platform": "psx",
            },
        }
        file_dict = {"file_name": "scph5501.bin", "md5": ""}
        result = plugin._enrich_firmware_file(file_dict)
        assert result["required"] is True
        assert result["description"] == "PS1 BIOS (USA)"

    def test_enrich_firmware_optional(self, plugin):
        """File in registry marked required=False."""
        plugin._bios_registry = {
            "platforms": {
                "dc": {
                    "optional_fw.bin": {
                        "description": "Optional debug firmware",
                        "required": False,
                        "md5": "",
                    },
                },
            },
        }
        plugin._bios_files_index = {
            "optional_fw.bin": {
                "description": "Optional debug firmware",
                "required": False,
                "md5": "",
                "platform": "dc",
            },
        }
        file_dict = {"file_name": "optional_fw.bin", "md5": ""}
        result = plugin._enrich_firmware_file(file_dict)
        assert result["required"] is False
        assert result["description"] == "Optional debug firmware"

    def test_enrich_firmware_unknown_defaults_not_required(self, plugin):
        """File NOT in registry defaults to required=False (unknown classification)."""
        plugin._bios_registry = {"platforms": {}}
        plugin._bios_files_index = {}
        file_dict = {"file_name": "unknown_bios.bin", "md5": ""}
        result = plugin._enrich_firmware_file(file_dict)
        assert result["required"] is False
        assert result["classification"] == "unknown"
        assert result["description"] == "unknown_bios.bin"

    def test_enrich_firmware_unknown_classification(self, plugin):
        """File NOT in registry gets classification 'unknown'."""
        plugin._bios_registry = {"platforms": {}}
        plugin._bios_files_index = {}
        file_dict = {"file_name": "mystery.bin", "md5": ""}
        result = plugin._enrich_firmware_file(file_dict)
        assert result["classification"] == "unknown"

    def test_enrich_firmware_required_classification(self, plugin):
        """File in registry with required=True gets classification 'required'."""
        plugin._bios_registry = {
            "platforms": {
                "psx": {
                    "scph5501.bin": {
                        "description": "PS1 BIOS",
                        "required": True,
                        "md5": "",
                    },
                },
            },
        }
        plugin._bios_files_index = {
            "scph5501.bin": {
                "description": "PS1 BIOS",
                "required": True,
                "md5": "",
                "platform": "psx",
            },
        }
        file_dict = {"file_name": "scph5501.bin", "md5": ""}
        result = plugin._enrich_firmware_file(file_dict)
        assert result["classification"] == "required"

    def test_enrich_firmware_optional_classification(self, plugin):
        """File in registry with required=False gets classification 'optional'."""
        plugin._bios_registry = {
            "platforms": {
                "dc": {
                    "optional_fw.bin": {
                        "description": "Optional firmware",
                        "required": False,
                        "md5": "",
                    },
                },
            },
        }
        plugin._bios_files_index = {
            "optional_fw.bin": {
                "description": "Optional firmware",
                "required": False,
                "md5": "",
                "platform": "dc",
            },
        }
        file_dict = {"file_name": "optional_fw.bin", "md5": ""}
        result = plugin._enrich_firmware_file(file_dict)
        assert result["classification"] == "optional"

    def test_hash_validation_match(self, plugin):
        """RomM md5 matches registry md5."""
        plugin._bios_registry = {
            "platforms": {
                "dc": {
                    "bios.bin": {
                        "description": "Test BIOS",
                        "required": True,
                        "md5": "abc123def456",
                    },
                },
            },
        }
        plugin._bios_files_index = {
            "bios.bin": {
                "description": "Test BIOS",
                "required": True,
                "md5": "abc123def456",
                "platform": "dc",
            },
        }
        file_dict = {"file_name": "bios.bin", "md5": "abc123def456"}
        result = plugin._enrich_firmware_file(file_dict)
        assert result["hash_valid"] is True

    def test_hash_validation_mismatch(self, plugin):
        """RomM md5 differs from registry md5."""
        plugin._bios_registry = {
            "platforms": {
                "dc": {
                    "bios.bin": {
                        "description": "Test BIOS",
                        "required": True,
                        "md5": "abc123def456",
                    },
                },
            },
        }
        plugin._bios_files_index = {
            "bios.bin": {
                "description": "Test BIOS",
                "required": True,
                "md5": "abc123def456",
                "platform": "dc",
            },
        }
        file_dict = {"file_name": "bios.bin", "md5": "000000000000"}
        result = plugin._enrich_firmware_file(file_dict)
        assert result["hash_valid"] is False

    def test_hash_validation_null(self, plugin):
        """No hash from either source results in hash_valid=None."""
        plugin._bios_registry = {
            "platforms": {
                "dc": {
                    "bios.bin": {
                        "description": "Test BIOS",
                        "required": True,
                        "md5": "",
                    },
                },
            },
        }
        plugin._bios_files_index = {
            "bios.bin": {
                "description": "Test BIOS",
                "required": True,
                "md5": "",
                "platform": "dc",
            },
        }
        file_dict = {"file_name": "bios.bin", "md5": ""}
        result = plugin._enrich_firmware_file(file_dict)
        assert result["hash_valid"] is None

    def test_hash_validation_null_no_registry_entry(self, plugin):
        """File not in registry and no RomM hash -> hash_valid=None."""
        plugin._bios_registry = {"platforms": {}}
        plugin._bios_files_index = {}
        file_dict = {"file_name": "bios.bin", "md5": ""}
        result = plugin._enrich_firmware_file(file_dict)
        assert result["hash_valid"] is None

    def test_hash_validation_case_insensitive(self, plugin):
        """Hash comparison is case-insensitive."""
        plugin._bios_registry = {
            "platforms": {
                "dc": {
                    "bios.bin": {
                        "description": "Test BIOS",
                        "required": True,
                        "md5": "ABC123DEF456",
                    },
                },
            },
        }
        plugin._bios_files_index = {
            "bios.bin": {
                "description": "Test BIOS",
                "required": True,
                "md5": "ABC123DEF456",
                "platform": "dc",
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
            "platforms": {
                "dc": {
                    "required1.bin": {"description": "Required BIOS 1", "required": True, "md5": ""},
                    "required2.bin": {"description": "Required BIOS 2", "required": True, "md5": ""},
                    "optional1.bin": {"description": "Optional firmware", "required": False, "md5": ""},
                },
            },
        }
        plugin._bios_files_index = {
            "required1.bin": {"description": "Required BIOS 1", "required": True, "md5": "", "platform": "dc"},
            "required2.bin": {"description": "Required BIOS 2", "required": True, "md5": "", "platform": "dc"},
            "optional1.bin": {"description": "Optional firmware", "required": False, "md5": "", "platform": "dc"},
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

        # Create downloaded required files (flat in bios root, no firmware_path in registry)
        bios_dir = tmp_path / "retrodeck" / "bios"
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
            "platforms": {
                "dc": {
                    "required1.bin": {"description": "Required BIOS 1", "required": True, "md5": ""},
                    "required2.bin": {"description": "Required BIOS 2", "required": True, "md5": ""},
                    "optional1.bin": {"description": "Optional firmware", "required": False, "md5": ""},
                },
            },
        }
        plugin._bios_files_index = {
            "required1.bin": {"description": "Required BIOS 1", "required": True, "md5": "", "platform": "dc"},
            "required2.bin": {"description": "Required BIOS 2", "required": True, "md5": "", "platform": "dc"},
            "optional1.bin": {"description": "Optional firmware", "required": False, "md5": "", "platform": "dc"},
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
            "platforms": {
                "dc": {
                    "bios.bin": {"description": "Dreamcast BIOS", "required": True, "md5": ""},
                },
            },
        }
        plugin._bios_files_index = {
            "bios.bin": {"description": "Dreamcast BIOS", "required": True, "md5": "", "platform": "dc"},
        }

        plugin.loop = MagicMock()
        plugin.loop.run_in_executor = AsyncMock(return_value=firmware_list)

        result = await plugin.check_platform_bios("dc")
        assert result["files"][0]["required"] is True
        assert result["files"][0]["description"] == "Dreamcast BIOS"

    @pytest.mark.asyncio
    async def test_check_platform_bios_unknown_count(self, plugin, tmp_path):
        """RomM has files not in registry -> unknown_count > 0."""
        from unittest.mock import AsyncMock, MagicMock
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        firmware_list = [
            {"id": 1, "file_name": "known.bin", "file_path": "bios/dc/known.bin", "file_size_bytes": 100, "md5_hash": ""},
            {"id": 2, "file_name": "mystery.bin", "file_path": "bios/dc/mystery.bin", "file_size_bytes": 200, "md5_hash": ""},
            {"id": 3, "file_name": "alien.bin", "file_path": "bios/dc/alien.bin", "file_size_bytes": 300, "md5_hash": ""},
        ]

        # Only "known.bin" is in the registry
        plugin._bios_registry = {
            "platforms": {
                "dc": {
                    "known.bin": {"description": "Known BIOS", "required": True, "md5": ""},
                },
            },
        }
        plugin._bios_files_index = {
            "known.bin": {"description": "Known BIOS", "required": True, "md5": "", "platform": "dc"},
        }

        plugin.loop = MagicMock()
        plugin.loop.run_in_executor = AsyncMock(return_value=firmware_list)

        result = await plugin.check_platform_bios("dc")
        assert result["needs_bios"] is True
        assert result["unknown_count"] == 2
        # Per-file classification
        classifications = {f["file_name"]: f["classification"] for f in result["files"]}
        assert classifications["known.bin"] == "required"
        assert classifications["mystery.bin"] == "unknown"
        assert classifications["alien.bin"] == "unknown"


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
            "platforms": {
                "dc": {
                    "required.bin": {"description": "Required BIOS", "required": True, "md5": ""},
                    "optional.bin": {"description": "Optional firmware", "required": False, "md5": ""},
                },
            },
        }
        plugin._bios_files_index = {
            "required.bin": {"description": "Required BIOS", "required": True, "md5": "", "platform": "dc"},
            "optional.bin": {"description": "Optional firmware", "required": False, "md5": "", "platform": "dc"},
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

        # Pre-create one required file so it's skipped (flat in bios root)
        bios_dir = tmp_path / "retrodeck" / "bios"
        bios_dir.mkdir(parents=True)
        (bios_dir / "existing.bin").write_bytes(b"\x00" * 100)

        firmware_list = [
            {"id": 1, "file_name": "existing.bin", "file_path": "bios/dc/existing.bin", "file_size_bytes": 100, "md5_hash": ""},
            {"id": 2, "file_name": "missing.bin", "file_path": "bios/dc/missing.bin", "file_size_bytes": 200, "md5_hash": ""},
        ]

        plugin._bios_registry = {
            "platforms": {
                "dc": {
                    "existing.bin": {"description": "Already downloaded", "required": True, "md5": ""},
                    "missing.bin": {"description": "Not yet downloaded", "required": True, "md5": ""},
                },
            },
        }
        plugin._bios_files_index = {
            "existing.bin": {"description": "Already downloaded", "required": True, "md5": "", "platform": "dc"},
            "missing.bin": {"description": "Not yet downloaded", "required": True, "md5": "", "platform": "dc"},
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


class TestCheckPlatformBiosOffline:
    """Tests for check_platform_bios registry fallback when RomM is offline."""

    @pytest.mark.asyncio
    async def test_offline_fallback_with_registry(self, plugin, tmp_path):
        """API fails but registry has entries — returns registry-based status."""
        from unittest.mock import patch
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        bios_dir = tmp_path / "bios"
        bios_dir.mkdir(parents=True)
        # Create one file present, one missing
        (bios_dir / "scph5501.bin").write_bytes(b"\x00" * 512)

        plugin._bios_registry = {
            "platforms": {
                "psx": {
                    "scph5501.bin": {
                        "description": "PS1 US BIOS",
                        "required": True,
                        "firmware_path": "scph5501.bin",
                    },
                    "scph5502.bin": {
                        "description": "PS1 EU BIOS",
                        "required": True,
                        "firmware_path": "scph5502.bin",
                    },
                    "scph1000.bin": {
                        "description": "PS1 JP BIOS",
                        "required": False,
                        "firmware_path": "scph1000.bin",
                    },
                }
            }
        }
        plugin._bios_files_index = {}
        for plat, files in plugin._bios_registry["platforms"].items():
            for fname, entry in files.items():
                plugin._bios_files_index[fname] = {**entry, "platform": plat}

        with patch.object(plugin, "_romm_request", side_effect=Exception("offline")), \
             patch("lib.retrodeck_config.get_bios_path", return_value=str(bios_dir)):
            result = await plugin.check_platform_bios("psx")

        assert result["needs_bios"] is True
        assert result["server_count"] == 3
        assert result["local_count"] == 1
        assert result["required_count"] == 2
        assert result["required_downloaded"] == 1
        assert len(result["files"]) == 3

    @pytest.mark.asyncio
    async def test_offline_no_registry_entries(self, plugin, tmp_path):
        """API fails and no registry entries — returns needs_bios False."""
        from unittest.mock import patch
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        plugin._bios_registry = {"platforms": {}}
        plugin._bios_files_index = {}

        with patch.object(plugin, "_romm_request", side_effect=Exception("offline")), \
             patch("lib.retrodeck_config.get_bios_path", return_value=str(tmp_path / "bios")):
            result = await plugin.check_platform_bios("n64")

        assert result["needs_bios"] is False

    @pytest.mark.asyncio
    async def test_offline_all_required_downloaded(self, plugin, tmp_path):
        """API fails, all required files present — all_downloaded True."""
        from unittest.mock import patch
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        bios_dir = tmp_path / "bios"
        dc_dir = bios_dir / "dc"
        dc_dir.mkdir(parents=True)
        (dc_dir / "dc_boot.bin").write_bytes(b"\x00" * 2048)

        plugin._bios_registry = {
            "platforms": {
                "dc": {
                    "dc_boot.bin": {
                        "description": "Dreamcast BIOS",
                        "required": True,
                        "firmware_path": "dc/dc_boot.bin",
                    },
                    "dc_flash.bin": {
                        "description": "Dreamcast Flash",
                        "required": False,
                        "firmware_path": "dc/dc_flash.bin",
                    },
                }
            }
        }
        plugin._bios_files_index = {}
        for plat, files in plugin._bios_registry["platforms"].items():
            for fname, entry in files.items():
                plugin._bios_files_index[fname] = {**entry, "platform": plat}

        with patch.object(plugin, "_romm_request", side_effect=Exception("offline")), \
             patch("lib.retrodeck_config.get_bios_path", return_value=str(bios_dir)):
            result = await plugin.check_platform_bios("dc")

        assert result["needs_bios"] is True
        assert result["server_count"] == 2
        assert result["local_count"] == 1
        assert result["required_count"] == 1
        assert result["required_downloaded"] == 1
        # all_downloaded is false because optional file is missing
        assert result["all_downloaded"] is False


class TestPerCoreFiltering:
    """Tests for per-core BIOS filtering in check_platform_bios and _enrich_firmware_file."""

    def test_enrich_uses_core_specific_required(self, plugin):
        """When core_so is provided, uses per-core required value."""
        plugin._bios_files_index = {
            "gba_bios.bin": {
                "description": "GBA BIOS",
                "required": True,  # OR-logic says required
                "md5": "",
                "platform": "gba",
                "cores": {
                    "mgba_libretro": {"required": False},
                    "gpsp_libretro": {"required": True},
                },
            },
        }
        # mGBA says optional
        file_dict = {"file_name": "gba_bios.bin", "md5": ""}
        result = plugin._enrich_firmware_file(file_dict, core_so="mgba_libretro")
        assert result["required"] is False
        assert result["classification"] == "optional"

    def test_enrich_gpsp_makes_required(self, plugin):
        """gpSP core marks gba_bios.bin as required."""
        plugin._bios_files_index = {
            "gba_bios.bin": {
                "description": "GBA BIOS",
                "required": True,
                "md5": "",
                "platform": "gba",
                "cores": {
                    "mgba_libretro": {"required": False},
                    "gpsp_libretro": {"required": True},
                },
            },
        }
        file_dict = {"file_name": "gba_bios.bin", "md5": ""}
        result = plugin._enrich_firmware_file(file_dict, core_so="gpsp_libretro")
        assert result["required"] is True
        assert result["classification"] == "required"

    def test_enrich_falls_back_without_core(self, plugin):
        """Without core_so, falls back to top-level OR-logic required."""
        plugin._bios_files_index = {
            "gba_bios.bin": {
                "description": "GBA BIOS",
                "required": True,
                "md5": "",
                "platform": "gba",
                "cores": {
                    "mgba_libretro": {"required": False},
                    "gpsp_libretro": {"required": True},
                },
            },
        }
        file_dict = {"file_name": "gba_bios.bin", "md5": ""}
        result = plugin._enrich_firmware_file(file_dict, core_so=None)
        assert result["required"] is True  # OR-logic fallback

    def test_enrich_unknown_core_uses_toplevel(self, plugin):
        """Core not in cores dict falls back to top-level required."""
        plugin._bios_files_index = {
            "gba_bios.bin": {
                "description": "GBA BIOS",
                "required": True,
                "md5": "",
                "platform": "gba",
                "cores": {
                    "mgba_libretro": {"required": False},
                },
            },
        }
        file_dict = {"file_name": "gba_bios.bin", "md5": ""}
        result = plugin._enrich_firmware_file(file_dict, core_so="unknown_core_libretro")
        assert result["required"] is True  # top-level OR fallback

    @pytest.mark.asyncio
    async def test_check_platform_bios_filters_by_core(self, plugin, tmp_path):
        """check_platform_bios returns all files but marks used_by_active correctly."""
        from unittest.mock import AsyncMock, MagicMock, patch
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        firmware_list = [
            {"id": 1, "file_name": "gba_bios.bin", "file_path": "bios/gba/gba_bios.bin", "file_size_bytes": 100, "md5_hash": ""},
            {"id": 2, "file_name": "gb_bios.bin", "file_path": "bios/gba/gb_bios.bin", "file_size_bytes": 200, "md5_hash": ""},
            {"id": 3, "file_name": "sgb_bios.bin", "file_path": "bios/gba/sgb_bios.bin", "file_size_bytes": 300, "md5_hash": ""},
        ]

        plugin._bios_registry = {
            "platforms": {
                "gba": {
                    "gba_bios.bin": {
                        "description": "GBA BIOS", "required": True, "firmware_path": "gba_bios.bin", "md5": "",
                        "cores": {"mgba_libretro": {"required": False}, "gpsp_libretro": {"required": True}},
                    },
                    "gb_bios.bin": {
                        "description": "GB BIOS", "required": False, "firmware_path": "gb_bios.bin", "md5": "",
                        "cores": {"gambatte_libretro": {"required": False}, "mgba_libretro": {"required": False}},
                    },
                    "sgb_bios.bin": {
                        "description": "SGB BIOS", "required": False, "firmware_path": "sgb_bios.bin", "md5": "",
                        "cores": {"mgba_libretro": {"required": False}},
                    },
                },
            },
        }
        plugin._bios_files_index = {
            "gba_bios.bin": {**plugin._bios_registry["platforms"]["gba"]["gba_bios.bin"], "platform": "gba"},
            "gb_bios.bin": {**plugin._bios_registry["platforms"]["gba"]["gb_bios.bin"], "platform": "gba"},
            "sgb_bios.bin": {**plugin._bios_registry["platforms"]["gba"]["sgb_bios.bin"], "platform": "gba"},
        }

        plugin.loop = MagicMock()
        plugin.loop.run_in_executor = AsyncMock(return_value=firmware_list)

        # gpSP only uses gba_bios.bin — all files returned but gb/sgb marked as not used by active
        with patch("lib.es_de_config.get_active_core", return_value=("gpsp_libretro", "gpSP")), \
             patch("lib.es_de_config.get_available_cores", return_value=[]):
            result = await plugin.check_platform_bios("gba")

        assert result["needs_bios"] is True
        file_names = [f["file_name"] for f in result["files"]]
        assert "gba_bios.bin" in file_names
        assert "gb_bios.bin" in file_names  # present but not used by active
        assert "sgb_bios.bin" in file_names  # present but not used by active
        assert result["server_count"] == 3
        assert result["active_core"] == "gpsp_libretro"
        assert result["active_core_label"] == "gpSP"
        # gpSP requires gba_bios.bin
        gba_file = [f for f in result["files"] if f["file_name"] == "gba_bios.bin"][0]
        assert gba_file["required"] is True
        assert gba_file["classification"] == "required"
        assert gba_file["used_by_active"] is True
        # gb_bios not used by gpSP
        gb_file = [f for f in result["files"] if f["file_name"] == "gb_bios.bin"][0]
        assert gb_file["used_by_active"] is False
        assert gb_file["cores"] == {"gambatte_libretro": {"required": False}, "mgba_libretro": {"required": False}}
        # required_count should only count files used by active core
        assert result["required_count"] == 1
        assert result["required_downloaded"] == 0

    @pytest.mark.asyncio
    async def test_check_platform_bios_mgba_all_optional(self, plugin, tmp_path):
        """mGBA shows files it uses but all as optional."""
        from unittest.mock import AsyncMock, MagicMock, patch
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        firmware_list = [
            {"id": 1, "file_name": "gba_bios.bin", "file_path": "bios/gba/gba_bios.bin", "file_size_bytes": 100, "md5_hash": ""},
            {"id": 2, "file_name": "gb_bios.bin", "file_path": "bios/gba/gb_bios.bin", "file_size_bytes": 200, "md5_hash": ""},
            {"id": 3, "file_name": "sgb_bios.bin", "file_path": "bios/gba/sgb_bios.bin", "file_size_bytes": 300, "md5_hash": ""},
        ]

        plugin._bios_registry = {
            "platforms": {
                "gba": {
                    "gba_bios.bin": {
                        "description": "GBA BIOS", "required": True, "firmware_path": "gba_bios.bin", "md5": "",
                        "cores": {"mgba_libretro": {"required": False}, "gpsp_libretro": {"required": True}},
                    },
                    "gb_bios.bin": {
                        "description": "GB BIOS", "required": False, "firmware_path": "gb_bios.bin", "md5": "",
                        "cores": {"mgba_libretro": {"required": False}},
                    },
                    "sgb_bios.bin": {
                        "description": "SGB BIOS", "required": False, "firmware_path": "sgb_bios.bin", "md5": "",
                        "cores": {"mgba_libretro": {"required": False}},
                    },
                },
            },
        }
        plugin._bios_files_index = {
            "gba_bios.bin": {**plugin._bios_registry["platforms"]["gba"]["gba_bios.bin"], "platform": "gba"},
            "gb_bios.bin": {**plugin._bios_registry["platforms"]["gba"]["gb_bios.bin"], "platform": "gba"},
            "sgb_bios.bin": {**plugin._bios_registry["platforms"]["gba"]["sgb_bios.bin"], "platform": "gba"},
        }

        plugin.loop = MagicMock()
        plugin.loop.run_in_executor = AsyncMock(return_value=firmware_list)

        # mGBA uses all 3 files, all optional
        with patch("lib.es_de_config.get_active_core", return_value=("mgba_libretro", "mGBA")), \
             patch("lib.es_de_config.get_available_cores", return_value=[]):
            result = await plugin.check_platform_bios("gba")

        assert result["needs_bios"] is True
        assert result["server_count"] == 3
        assert result["required_count"] == 0  # all optional for mGBA
        for f in result["files"]:
            assert f["classification"] == "optional"
            assert f["used_by_active"] is True

    @pytest.mark.asyncio
    async def test_check_platform_bios_no_core_shows_all(self, plugin, tmp_path):
        """When core resolution fails, shows all files with OR-logic."""
        from unittest.mock import AsyncMock, MagicMock, patch
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        firmware_list = [
            {"id": 1, "file_name": "gba_bios.bin", "file_path": "bios/gba/gba_bios.bin", "file_size_bytes": 100, "md5_hash": ""},
        ]

        plugin._bios_registry = {
            "platforms": {
                "gba": {
                    "gba_bios.bin": {
                        "description": "GBA BIOS", "required": True, "firmware_path": "gba_bios.bin", "md5": "",
                        "cores": {"mgba_libretro": {"required": False}},
                    },
                },
            },
        }
        plugin._bios_files_index = {
            "gba_bios.bin": {**plugin._bios_registry["platforms"]["gba"]["gba_bios.bin"], "platform": "gba"},
        }

        plugin.loop = MagicMock()
        plugin.loop.run_in_executor = AsyncMock(return_value=firmware_list)

        # Core resolution fails
        with patch("lib.es_de_config.get_active_core", return_value=(None, None)), \
             patch("lib.es_de_config.get_available_cores", return_value=[]):
            result = await plugin.check_platform_bios("gba")

        assert result["needs_bios"] is True
        assert result["server_count"] == 1
        assert result["active_core"] is None
        # Falls back to OR-logic: required=True
        assert result["files"][0]["required"] is True

    @pytest.mark.asyncio
    async def test_offline_fallback_includes_all_with_used_by_active(self, plugin, tmp_path):
        """Offline registry fallback returns all files with used_by_active flag."""
        from unittest.mock import AsyncMock, MagicMock, patch
        import decky
        decky.DECKY_USER_HOME = str(tmp_path)

        bios_dir = tmp_path / "bios"
        bios_dir.mkdir()
        (bios_dir / "gba_bios.bin").write_bytes(b"\x00" * 100)

        plugin._bios_registry = {
            "platforms": {
                "gba": {
                    "gba_bios.bin": {
                        "description": "GBA BIOS", "required": True, "firmware_path": "gba_bios.bin", "md5": "",
                        "cores": {"gpsp_libretro": {"required": True}},
                    },
                    "gb_bios.bin": {
                        "description": "GB BIOS", "required": False, "firmware_path": "gb_bios.bin", "md5": "",
                        "cores": {"mgba_libretro": {"required": False}},
                    },
                },
            },
        }
        plugin._bios_files_index = {}

        plugin.loop = MagicMock()
        plugin.loop.run_in_executor = AsyncMock(side_effect=Exception("offline"))

        with patch("lib.es_de_config.get_active_core", return_value=("gpsp_libretro", "gpSP")), \
             patch("lib.es_de_config.get_available_cores", return_value=[]), \
             patch("lib.firmware.retrodeck_config.get_bios_path", return_value=str(bios_dir)):
            result = await plugin.check_platform_bios("gba")

        assert result["needs_bios"] is True
        file_names = [f["file_name"] for f in result["files"]]
        assert "gba_bios.bin" in file_names
        assert "gb_bios.bin" in file_names  # present but not used by active
        # Check used_by_active flags
        gba_file = [f for f in result["files"] if f["file_name"] == "gba_bios.bin"][0]
        assert gba_file["used_by_active"] is True
        gb_file = [f for f in result["files"] if f["file_name"] == "gb_bios.bin"][0]
        assert gb_file["used_by_active"] is False
