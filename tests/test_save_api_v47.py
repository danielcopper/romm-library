"""Tests for SaveApiV47 adapter."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from adapters.romm.save_api.v47 import SaveApiV47


@pytest.fixture()
def mock_client():
    client = MagicMock()
    client.download = MagicMock()
    client.request = MagicMock(return_value=[])
    client.upload_multipart = MagicMock(return_value={})
    client.post_json = MagicMock(return_value={})
    client.put_json = MagicMock(return_value={})
    return client


@pytest.fixture()
def api(mock_client):
    return SaveApiV47(mock_client)


@pytest.mark.asyncio()
async def test_download_save_uses_content_endpoint(api, mock_client):
    """download_save should use /api/saves/{id}/content directly."""
    await api.download_save(42, "/tmp/test.srm")
    mock_client.download.assert_called_once_with("/api/saves/42/content", "/tmp/test.srm")


@pytest.mark.asyncio()
async def test_list_saves_inherited(api, mock_client):
    """list_saves is inherited from v46 and works the same."""
    mock_client.request.return_value = [{"id": 1, "rom_id": 5}]
    result = await api.list_saves(5)
    assert result == [{"id": 1, "rom_id": 5}]
    mock_client.request.assert_called_once_with("/api/saves?rom_id=5")


@pytest.mark.asyncio()
async def test_get_save_metadata_inherited(api, mock_client):
    """get_save_metadata is inherited from v46."""
    mock_client.request.return_value = {"id": 10, "file_name": "test.srm"}
    result = await api.get_save_metadata(10)
    assert result == {"id": 10, "file_name": "test.srm"}


@pytest.mark.asyncio()
async def test_upload_save_inherited(api, mock_client):
    """upload_save is inherited from v46."""
    mock_client.upload_multipart.return_value = {"id": 1}
    result = await api.upload_save(5, "/tmp/test.srm", "retroarch")
    assert result == {"id": 1}
