"""Tests for RommApiV47 — verifies v47 overrides and base method inheritance."""

from __future__ import annotations

from unittest.mock import MagicMock

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
