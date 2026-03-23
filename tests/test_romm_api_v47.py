"""Tests for RommApiV47 — verifies v47 overrides and base method inheritance."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from adapters.romm.api_v47 import RommApiV47


def _make_api():
    client = MagicMock()
    client.request = MagicMock()
    client.download = MagicMock()
    client.post_json = MagicMock()
    client.put_json = MagicMock()
    client.upload_multipart = MagicMock()
    return RommApiV47(client), client


class TestDownloadSave:
    def test_uses_content_endpoint(self):
        api, client = _make_api()
        api.download_save(99, "/tmp/save.srm")
        client.download.assert_called_once_with("/api/saves/99/content", "/tmp/save.srm")

    def test_no_metadata_round_trip(self):
        """v47 should NOT call request() to fetch metadata first."""
        api, client = _make_api()
        api.download_save(5, "/tmp/save.srm")
        client.request.assert_not_called()


class TestRegisterDevice:
    def test_posts_to_devices_endpoint(self):
        api, client = _make_api()
        client.post_json.return_value = {
            "id": "abc-123",
            "name": "steamdeck",
            "created_at": "2026-01-01T00:00:00Z",
        }
        result = api.register_device("steamdeck", "linux", "decky-romm-sync", "0.13.0")
        client.post_json.assert_called_once_with(
            "/api/devices",
            {
                "name": "steamdeck",
                "platform": "linux",
                "client": "decky-romm-sync",
                "version": "0.13.0",
            },
        )
        assert result["id"] == "abc-123"

    def test_returns_full_response(self):
        api, client = _make_api()
        expected = {"id": "xyz", "name": "deck", "created_at": "2026-03-23T12:00:00Z"}
        client.post_json.return_value = expected
        result = api.register_device("deck", "linux", "decky", "1.0")
        assert result == expected


class TestListSavesV47:
    def test_base_call_unchanged(self):
        """Calling with just rom_id behaves like v46."""
        api, client = _make_api()
        client.request.return_value = [{"id": 1}]
        result = api.list_saves(42)
        client.request.assert_called_once_with("/api/saves?rom_id=42")
        assert result == [{"id": 1}]

    def test_with_device_id(self):
        api, client = _make_api()
        client.request.return_value = [{"id": 1, "device_syncs": []}]
        api.list_saves(42, device_id="abc-123")
        client.request.assert_called_once_with("/api/saves?rom_id=42&device_id=abc-123")

    def test_with_slot(self):
        api, client = _make_api()
        client.request.return_value = []
        api.list_saves(42, slot="default")
        client.request.assert_called_once_with("/api/saves?rom_id=42&slot=default")

    def test_with_device_id_and_slot(self):
        api, client = _make_api()
        client.request.return_value = []
        api.list_saves(42, device_id="abc", slot="default")
        client.request.assert_called_once_with("/api/saves?rom_id=42&device_id=abc&slot=default")

    def test_non_list_returns_empty(self):
        api, client = _make_api()
        client.request.return_value = {"error": "bad"}
        assert api.list_saves(42, device_id="abc") == []


class TestUploadSaveV47:
    def test_base_call_unchanged(self):
        """Calling with just base params behaves like v46."""
        api, client = _make_api()
        client.upload_multipart.return_value = {"id": 1}
        result = api.upload_save(42, "/tmp/save.srm", "retroarch-mgba")
        client.upload_multipart.assert_called_once_with(
            "/api/saves?rom_id=42&emulator=retroarch-mgba",
            "/tmp/save.srm",
            method="POST",
        )
        assert result == {"id": 1}

    def test_put_with_save_id(self):
        api, client = _make_api()
        client.upload_multipart.return_value = {"id": 5}
        api.upload_save(42, "/tmp/save.srm", "retroarch-mgba", save_id=5)
        client.upload_multipart.assert_called_once_with(
            "/api/saves/5?rom_id=42&emulator=retroarch-mgba",
            "/tmp/save.srm",
            method="PUT",
        )

    def test_with_device_id(self):
        api, client = _make_api()
        client.upload_multipart.return_value = {"id": 1}
        api.upload_save(42, "/tmp/save.srm", "retroarch-mgba", device_id="abc-123")
        path = client.upload_multipart.call_args[0][0]
        assert "device_id=abc-123" in path

    def test_with_slot(self):
        api, client = _make_api()
        client.upload_multipart.return_value = {"id": 1}
        api.upload_save(42, "/tmp/save.srm", "retroarch-mgba", slot="default")
        path = client.upload_multipart.call_args[0][0]
        assert "slot=default" in path

    def test_with_overwrite_true(self):
        api, client = _make_api()
        client.upload_multipart.return_value = {"id": 1}
        api.upload_save(42, "/tmp/save.srm", "retroarch-mgba", overwrite=True)
        path = client.upload_multipart.call_args[0][0]
        assert "overwrite=true" in path

    def test_overwrite_false_not_in_query(self):
        """overwrite=false is the default — don't clutter the query string."""
        api, client = _make_api()
        client.upload_multipart.return_value = {"id": 1}
        api.upload_save(42, "/tmp/save.srm", "retroarch-mgba", overwrite=False)
        path = client.upload_multipart.call_args[0][0]
        assert "overwrite" not in path

    def test_all_params_combined(self):
        api, client = _make_api()
        client.upload_multipart.return_value = {"id": 1}
        api.upload_save(
            42,
            "/tmp/save.srm",
            "retroarch-mgba",
            save_id=5,
            device_id="abc",
            slot="default",
            overwrite=True,
        )
        path = client.upload_multipart.call_args[0][0]
        assert path.startswith("/api/saves/5?")
        assert "rom_id=42" in path
        assert "emulator=retroarch-mgba" in path
        assert "device_id=abc" in path
        assert "slot=default" in path
        assert "overwrite=true" in path

    def test_409_raises_conflict_error(self):
        """409 from server propagates as RommConflictError (handled by RommHttpAdapter)."""
        from lib.errors import RommConflictError

        api, client = _make_api()
        client.upload_multipart.side_effect = RommConflictError("HTTP 409: Conflict", url="/api/saves", method="POST")
        with pytest.raises(RommConflictError):
            api.upload_save(42, "/tmp/save.srm", "retroarch-mgba", device_id="abc")

    def test_encodes_emulator(self):
        api, client = _make_api()
        client.upload_multipart.return_value = {"id": 1}
        api.upload_save(42, "/tmp/save.srm", "retro arch/core")
        path = client.upload_multipart.call_args[0][0]
        assert "emulator=retro%20arch/core" in path


class TestInheritsBaseMethods:
    def test_get_rom(self):
        api, client = _make_api()
        client.request.return_value = {"id": 42, "name": "Zelda"}
        result = api.get_rom(42)
        client.request.assert_called_once_with("/api/roms/42")
        assert result["id"] == 42

    def test_list_platforms(self):
        api, client = _make_api()
        client.request.return_value = [{"id": 1, "slug": "snes"}]
        result = api.list_platforms()
        client.request.assert_called_once_with("/api/platforms")
        assert result == [{"id": 1, "slug": "snes"}]

    def test_heartbeat(self):
        api, client = _make_api()
        client.request.return_value = {"version": "4.7.0"}
        result = api.heartbeat()
        client.request.assert_called_once_with("/api/heartbeat")
        assert result == {"version": "4.7.0"}
