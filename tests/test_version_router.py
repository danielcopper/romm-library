"""Tests for VersionRouter."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from adapters.romm.save_api.v46 import SaveApiV46
from adapters.romm.save_api.v47 import SaveApiV47
from adapters.romm.version_router import VersionRouter


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
def router(mock_client):
    return VersionRouter(mock_client)


# -- Version switching --


def test_default_is_v46(router):
    assert isinstance(router._active, SaveApiV46)


def test_set_version_470_switches_to_v47(router):
    router.set_version("4.7.0")
    assert isinstance(router._active, SaveApiV47)


def test_set_version_461_stays_v46(router):
    router.set_version("4.6.1")
    assert isinstance(router._active, SaveApiV46)


def test_set_version_460_stays_v46(router):
    router.set_version("4.6.0")
    assert isinstance(router._active, SaveApiV46)


def test_set_version_480_uses_v47(router):
    router.set_version("4.8.0")
    assert isinstance(router._active, SaveApiV47)


def test_set_version_development_uses_v47(router):
    router.set_version("development")
    assert isinstance(router._active, SaveApiV47)


def test_set_version_empty_stays_v46(router):
    router.set_version("")
    assert isinstance(router._active, SaveApiV46)


def test_set_version_garbage_stays_v46(router):
    router.set_version("not-a-version")
    assert isinstance(router._active, SaveApiV46)


def test_set_version_can_be_called_multiple_times(router):
    router.set_version("4.7.0")
    assert isinstance(router._active, SaveApiV47)
    router.set_version("4.6.1")
    assert isinstance(router._active, SaveApiV46)
    router.set_version("development")
    assert isinstance(router._active, SaveApiV47)


# -- Delegation --


@pytest.mark.asyncio()
async def test_download_save_delegates_v46(router, mock_client):
    """Default (v46) download goes through metadata workaround."""
    mock_client.request.return_value = {"download_path": "/saves/test.srm"}
    await router.download_save(1, "/tmp/test.srm")
    # v46 fetches metadata first
    mock_client.request.assert_called_with("/api/saves/1")


@pytest.mark.asyncio()
async def test_download_save_delegates_v47(router, mock_client):
    """After set_version(4.7.0), download uses /content endpoint."""
    router.set_version("4.7.0")
    await router.download_save(1, "/tmp/test.srm")
    mock_client.download.assert_called_once_with("/api/saves/1/content", "/tmp/test.srm")


@pytest.mark.asyncio()
async def test_list_saves_delegates(router, mock_client):
    mock_client.request.return_value = [{"id": 1}]
    result = await router.list_saves(5)
    assert result == [{"id": 1}]


@pytest.mark.asyncio()
async def test_upload_save_delegates(router, mock_client):
    mock_client.upload_multipart.return_value = {"id": 1}
    result = await router.upload_save(5, "/tmp/test.srm", "retroarch")
    assert result == {"id": 1}


@pytest.mark.asyncio()
async def test_get_save_metadata_delegates(router, mock_client):
    mock_client.request.return_value = {"id": 10}
    result = await router.get_save_metadata(10)
    assert result == {"id": 10}


@pytest.mark.asyncio()
async def test_get_rom_detail_delegates(router, mock_client):
    mock_client.request.return_value = {"id": 5, "name": "Test ROM"}
    result = await router.get_rom_detail(5)
    assert result == {"id": 5, "name": "Test ROM"}


@pytest.mark.asyncio()
async def test_create_note_delegates(router, mock_client):
    mock_client.post_json.return_value = {"id": 1}
    result = await router.create_note(5, {"body": "test"})
    assert result == {"id": 1}


@pytest.mark.asyncio()
async def test_update_note_delegates(router, mock_client):
    mock_client.put_json.return_value = {"id": 1}
    result = await router.update_note(5, 1, {"body": "updated"})
    assert result == {"id": 1}
