"""Tests for RommApiBase — verifies correct URL construction and transport delegation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from adapters.romm.api_base import RommApiBase


@pytest.fixture()
def client():
    mock = MagicMock()
    mock.request = MagicMock()
    mock.download = MagicMock()
    mock.post_json = MagicMock()
    mock.put_json = MagicMock()
    mock.upload_multipart = MagicMock()
    return mock


@pytest.fixture()
def api(client):
    return RommApiBase(client)


class TestSetVersion:
    def test_no_op(self, api):
        """set_version is a no-op on the base class."""
        api.set_version("4.6.1")  # should not raise


class TestHeartbeat:
    def test_path(self, api, client):
        client.request.return_value = {"version": "4.6.1"}
        result = api.heartbeat()
        client.request.assert_called_once_with("/api/heartbeat")
        assert result == {"version": "4.6.1"}


class TestListPlatforms:
    def test_path(self, api, client):
        client.request.return_value = [{"id": 1, "slug": "snes"}]
        result = api.list_platforms()
        client.request.assert_called_once_with("/api/platforms")
        assert result == [{"id": 1, "slug": "snes"}]


class TestGetCurrentUser:
    def test_path(self, api, client):
        client.request.return_value = {"id": 1, "username": "admin"}
        result = api.get_current_user()
        client.request.assert_called_once_with("/api/users/me")
        assert result == {"id": 1, "username": "admin"}


class TestGetRom:
    def test_path(self, api, client):
        client.request.return_value = {"id": 42, "name": "Zelda"}
        result = api.get_rom(42)
        client.request.assert_called_once_with("/api/roms/42")
        assert result["id"] == 42


class TestListRoms:
    def test_default_params(self, api, client):
        client.request.return_value = {"items": [], "total": 0}
        api.list_roms(5)
        client.request.assert_called_once_with("/api/roms?platform_ids=5&limit=50&offset=0")

    def test_custom_params(self, api, client):
        client.request.return_value = {"items": [], "total": 0}
        api.list_roms(3, limit=25, offset=10)
        client.request.assert_called_once_with("/api/roms?platform_ids=3&limit=25&offset=10")


class TestListRomsUpdatedAfter:
    def test_encodes_timestamp(self, api, client):
        client.request.return_value = {"items": [], "total": 0}
        api.list_roms_updated_after(5, "2024-01-01T00:00:00+00:00")
        args = client.request.call_args[0][0]
        assert "platform_ids=5" in args
        assert "updated_after=2024-01-01T00%3A00%3A00%2B00%3A00" in args

    def test_default_params(self, api, client):
        client.request.return_value = {"items": [], "total": 0}
        api.list_roms_updated_after(1, "2024-06-15")
        args = client.request.call_args[0][0]
        assert "limit=1" in args
        assert "offset=0" in args


class TestDownloadRomContent:
    def test_encodes_filename(self, api, client):
        api.download_rom_content(10, "My Game (USA).zip", "/tmp/dest.zip")
        client.download.assert_called_once()
        path = client.download.call_args[0][0]
        assert path == "/api/roms/10/content/My%20Game%20%28USA%29.zip"
        assert client.download.call_args[0][1] == "/tmp/dest.zip"

    def test_passes_progress_callback(self, api, client):
        cb = MagicMock()
        api.download_rom_content(10, "game.zip", "/tmp/dest.zip", progress_callback=cb)
        assert client.download.call_args[0][2] is cb


class TestDownloadCover:
    def test_passes_url_directly(self, api, client):
        api.download_cover("/assets/covers/game.jpg", "/tmp/cover.jpg")
        client.download.assert_called_once_with("/assets/covers/game.jpg", "/tmp/cover.jpg")


class TestListFirmware:
    def test_path(self, api, client):
        client.request.return_value = [{"id": 1}]
        result = api.list_firmware()
        client.request.assert_called_once_with("/api/firmware")
        assert result == [{"id": 1}]


class TestGetFirmware:
    def test_path(self, api, client):
        client.request.return_value = {"id": 7, "filename": "bios.bin"}
        result = api.get_firmware(7)
        client.request.assert_called_once_with("/api/firmware/7")
        assert result["id"] == 7


class TestDownloadFirmware:
    def test_encodes_filename(self, api, client):
        api.download_firmware(7, "bios file.bin", "/tmp/bios.bin")
        client.download.assert_called_once()
        path = client.download.call_args[0][0]
        assert path == "/api/firmware/7/content/bios%20file.bin"
        assert client.download.call_args[0][1] == "/tmp/bios.bin"


class TestListSaves:
    def test_returns_list(self, api, client):
        client.request.return_value = [{"id": 1}]
        result = api.list_saves(42)
        client.request.assert_called_once_with("/api/saves?rom_id=42")
        assert result == [{"id": 1}]

    def test_non_list_returns_empty(self, api, client):
        client.request.return_value = {"error": "something"}
        result = api.list_saves(42)
        assert result == []


class TestUploadSave:
    def test_post_when_no_save_id(self, api, client):
        client.upload_multipart.return_value = {"id": 1}
        result = api.upload_save(42, "/tmp/save.srm", "retroarch")
        client.upload_multipart.assert_called_once_with(
            "/api/saves?rom_id=42&emulator=retroarch",
            "/tmp/save.srm",
            method="POST",
        )
        assert result == {"id": 1}

    def test_put_when_save_id_given(self, api, client):
        client.upload_multipart.return_value = {"id": 5}
        result = api.upload_save(42, "/tmp/save.srm", "retroarch", save_id=5)
        client.upload_multipart.assert_called_once_with(
            "/api/saves/5?rom_id=42&emulator=retroarch",
            "/tmp/save.srm",
            method="PUT",
        )
        assert result == {"id": 5}

    def test_encodes_emulator(self, api, client):
        client.upload_multipart.return_value = {"id": 1}
        api.upload_save(42, "/tmp/save.srm", "retro arch/core")
        path = client.upload_multipart.call_args[0][0]
        assert "emulator=retro%20arch/core" in path


class TestDownloadSave:
    def test_two_step_metadata_then_download(self, api, client):
        client.request.return_value = {
            "id": 5,
            "download_path": "/saves/my save (1).srm",
        }
        api.download_save(5, "/tmp/save.srm")
        client.request.assert_called_once_with("/api/saves/5")
        client.download.assert_called_once_with("/saves/my%20save%20%281%29.srm", "/tmp/save.srm")

    def test_raises_when_no_download_path(self, api, client):
        client.request.return_value = {"id": 5}
        with pytest.raises(ValueError, match="no download_path"):
            api.download_save(5, "/tmp/save.srm")

    def test_raises_when_empty_download_path(self, api, client):
        client.request.return_value = {"id": 5, "download_path": ""}
        with pytest.raises(ValueError, match="no download_path"):
            api.download_save(5, "/tmp/save.srm")


class TestGetSaveMetadata:
    def test_path(self, api, client):
        client.request.return_value = {"id": 5, "filename": "save.srm"}
        result = api.get_save_metadata(5)
        client.request.assert_called_once_with("/api/saves/5")
        assert result["id"] == 5


class TestGetRomWithNotes:
    def test_uses_rom_detail_endpoint(self, api, client):
        """v46: /api/roms/{id}/notes returns 500, so we use ROM detail."""
        client.request.return_value = {"id": 42, "all_user_notes": []}
        result = api.get_rom_with_notes(42)
        client.request.assert_called_once_with("/api/roms/42")
        assert result["id"] == 42


class TestCreateNote:
    def test_path(self, api, client):
        client.post_json.return_value = {"id": 1}
        data = {"body": "playtime: 120"}
        result = api.create_note(42, data)
        client.post_json.assert_called_once_with("/api/roms/42/notes", data)
        assert result == {"id": 1}


class TestUpdateNote:
    def test_path(self, api, client):
        client.put_json.return_value = {"id": 10}
        data = {"body": "playtime: 240"}
        result = api.update_note(42, 10, data)
        client.put_json.assert_called_once_with("/api/roms/42/notes/10", data)
        assert result == {"id": 10}
