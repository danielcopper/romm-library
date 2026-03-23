"""Tests for ApiRouter — version-aware RommApiProtocol delegation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from adapters.romm.api_router import ApiRouter
from lib.errors import RommUnsupportedError


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def router(mock_client):
    return ApiRouter(mock_client)


# -- Version routing --


class TestSetVersion:
    def test_default_is_v46(self, router):
        """Before set_version, _active should be the v46 impl."""
        assert router._active is router._v46

    def test_v470_switches_to_v47(self, router):
        router.set_version("4.7.0")
        assert router._active is router._v47

    def test_v471_switches_to_v47(self, router):
        router.set_version("4.7.1")
        assert router._active is router._v47

    def test_v480_switches_to_v47(self, router):
        router.set_version("4.8.0")
        assert router._active is router._v47

    def test_v461_stays_v46(self, router):
        router.set_version("4.6.1")
        assert router._active is router._v46

    def test_v460_stays_v46(self, router):
        router.set_version("4.6.0")
        assert router._active is router._v46

    def test_development_switches_to_v47(self, router):
        router.set_version("development")
        assert router._active is router._v47

    def test_empty_string_stays_v46(self, router):
        router.set_version("")
        assert router._active is router._v46

    def test_garbage_stays_v46(self, router):
        router.set_version("not-a-version")
        assert router._active is router._v46

    def test_can_switch_back_to_v46(self, router):
        router.set_version("4.7.0")
        assert router._active is router._v47
        router.set_version("4.6.1")
        assert router._active is router._v46


# -- Delegation --


class TestDelegation:
    """Verify all 18 protocol methods delegate to the active implementation."""

    def test_heartbeat(self, router, mock_client):
        mock_client.request.return_value = {"version": "4.7.0"}
        result = router.heartbeat()
        assert result == {"version": "4.7.0"}
        mock_client.request.assert_called_with("/api/heartbeat")

    def test_list_platforms(self, router, mock_client):
        mock_client.request.return_value = [{"id": 1}]
        result = router.list_platforms()
        assert result == [{"id": 1}]
        mock_client.request.assert_called_with("/api/platforms")

    def test_get_current_user(self, router, mock_client):
        mock_client.request.return_value = {"username": "test"}
        result = router.get_current_user()
        assert result == {"username": "test"}
        mock_client.request.assert_called_with("/api/users/me")

    def test_get_rom(self, router, mock_client):
        mock_client.request.return_value = {"id": 42}
        result = router.get_rom(42)
        assert result == {"id": 42}
        mock_client.request.assert_called_with("/api/roms/42")

    def test_list_roms(self, router, mock_client):
        mock_client.request.return_value = {"items": [], "total": 0}
        result = router.list_roms(1, limit=10, offset=5)
        assert result == {"items": [], "total": 0}
        mock_client.request.assert_called_with("/api/roms?platform_ids=1&limit=10&offset=5")

    def test_list_roms_updated_after(self, router, mock_client):
        mock_client.request.return_value = {"items": [], "total": 0}
        result = router.list_roms_updated_after(1, "2024-01-01T00:00:00", limit=5, offset=0)
        assert result == {"items": [], "total": 0}

    def test_download_rom_content(self, router, mock_client):
        cb = MagicMock()
        router.download_rom_content(42, "game.zip", "/tmp/dest", cb)
        mock_client.download.assert_called_once()

    def test_download_cover(self, router, mock_client):
        router.download_cover("/covers/img.jpg", "/tmp/cover.jpg")
        mock_client.download.assert_called_with("/covers/img.jpg", "/tmp/cover.jpg")

    def test_list_firmware(self, router, mock_client):
        mock_client.request.return_value = [{"id": 1}]
        result = router.list_firmware()
        assert result == [{"id": 1}]
        mock_client.request.assert_called_with("/api/firmware")

    def test_get_firmware(self, router, mock_client):
        mock_client.request.return_value = {"id": 5}
        result = router.get_firmware(5)
        assert result == {"id": 5}
        mock_client.request.assert_called_with("/api/firmware/5")

    def test_download_firmware(self, router, mock_client):
        router.download_firmware(5, "bios.bin", "/tmp/bios.bin")
        mock_client.download.assert_called_once()

    def test_list_saves(self, router, mock_client):
        mock_client.request.return_value = [{"id": 1}]
        result = router.list_saves(42)
        assert result == [{"id": 1}]
        mock_client.request.assert_called_with("/api/saves?rom_id=42")

    def test_upload_save_create(self, router, mock_client):
        mock_client.upload_multipart.return_value = {"id": 1}
        result = router.upload_save(42, "/tmp/save.srm", "retroarch")
        assert result == {"id": 1}
        mock_client.upload_multipart.assert_called_once()

    def test_upload_save_update(self, router, mock_client):
        mock_client.upload_multipart.return_value = {"id": 99}
        result = router.upload_save(42, "/tmp/save.srm", "retroarch", save_id=99)
        assert result == {"id": 99}

    def test_download_save_base(self, router, mock_client):
        """Base (v46) downloads via metadata + download_path."""
        mock_client.request.return_value = {"download_path": "/saves/file.srm"}
        router.download_save(1, "/tmp/save.srm")
        assert mock_client.download.called

    def test_download_save_v47(self, router, mock_client):
        """V47 downloads directly via /content endpoint."""
        router.set_version("4.7.0")
        router.download_save(1, "/tmp/save.srm")
        mock_client.download.assert_called_with("/api/saves/1/content", "/tmp/save.srm")

    def test_get_save_metadata(self, router, mock_client):
        mock_client.request.return_value = {"id": 1}
        result = router.get_save_metadata(1)
        assert result == {"id": 1}
        mock_client.request.assert_called_with("/api/saves/1")

    def test_get_rom_with_notes(self, router, mock_client):
        mock_client.request.return_value = {"id": 42, "all_user_notes": []}
        result = router.get_rom_with_notes(42)
        assert result == {"id": 42, "all_user_notes": []}
        mock_client.request.assert_called_with("/api/roms/42")

    def test_create_note(self, router, mock_client):
        mock_client.post_json.return_value = {"id": 1}
        result = router.create_note(42, {"body": "test"})
        assert result == {"id": 1}
        mock_client.post_json.assert_called_with("/api/roms/42/notes", {"body": "test"})

    def test_update_note(self, router, mock_client):
        mock_client.put_json.return_value = {"id": 1}
        result = router.update_note(42, 1, {"body": "updated"})
        assert result == {"id": 1}
        mock_client.put_json.assert_called_with("/api/roms/42/notes/1", {"body": "updated"})


# -- __getattr__ safety net --


class TestGetattr:
    def test_unknown_attr_raises_unsupported(self, router):
        with pytest.raises(RommUnsupportedError) as exc_info:
            router.some_future_method()
        assert exc_info.value.feature == "some_future_method"

    def test_unknown_attr_message(self, router):
        with pytest.raises(RommUnsupportedError, match="some_future_method"):
            router.some_future_method()

    def test_unknown_attr_is_romm_api_error(self, router):
        with pytest.raises(RommUnsupportedError) as exc_info:
            _ = router.nonexistent
        assert exc_info.value.min_version == "unknown"

    def test_register_device_raises_on_v46(self, router):
        with pytest.raises(RommUnsupportedError):
            router.register_device("deck", "linux", "decky", "1.0")


# -- supports_device_sync --


class TestSupportsDeviceSync:
    def test_false_by_default(self, router):
        assert router.supports_device_sync() is False

    def test_false_on_v46(self, router):
        router.set_version("4.6.1")
        assert router.supports_device_sync() is False

    def test_true_on_v47(self, router):
        router.set_version("4.7.0")
        assert router.supports_device_sync() is True

    def test_true_on_development(self, router):
        router.set_version("development")
        assert router.supports_device_sync() is True

    def test_switches_back_to_false(self, router):
        router.set_version("4.7.0")
        assert router.supports_device_sync() is True
        router.set_version("4.6.1")
        assert router.supports_device_sync() is False


# -- Delegation works on both versions --


class TestDelegationBothVersions:
    """Ensure delegation works after switching versions."""

    def test_heartbeat_on_base(self, router, mock_client):
        mock_client.request.return_value = {"version": "4.6.1"}
        router.set_version("4.6.1")
        result = router.heartbeat()
        assert result == {"version": "4.6.1"}

    def test_heartbeat_on_v47(self, router, mock_client):
        mock_client.request.return_value = {"version": "4.7.0"}
        router.set_version("4.7.0")
        result = router.heartbeat()
        assert result == {"version": "4.7.0"}

    def test_list_platforms_on_both(self, router, mock_client):
        mock_client.request.return_value = [{"id": 1}]

        router.set_version("4.6.1")
        assert router.list_platforms() == [{"id": 1}]

        router.set_version("4.7.0")
        assert router.list_platforms() == [{"id": 1}]
