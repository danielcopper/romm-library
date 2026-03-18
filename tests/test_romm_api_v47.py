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
