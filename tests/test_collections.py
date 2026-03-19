"""Tests for collection-related methods in LibraryService.

Covers get_collections(), save_collection_sync(), set_all_collections_sync(),
and _fetch_collection_roms().
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.steam_config import SteamConfigAdapter
from lib.errors import RommUnsupportedError

# conftest.py patches decky before this import
from main import Plugin
from services.library import LibraryService
from services.metadata import MetadataService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def plugin():
    p = Plugin()
    p.settings = {"romm_url": "", "romm_user": "", "romm_pass": "", "enabled_platforms": {}}
    p._romm_api = MagicMock()
    p._state = {"shortcut_registry": {}, "installed_roms": {}, "last_sync": None, "sync_stats": {}}
    p._metadata_cache = {}

    import decky

    steam_config = SteamConfigAdapter(user_home=decky.DECKY_USER_HOME, logger=decky.logger)
    p._steam_config = steam_config

    metadata_service = MetadataService(
        romm_api=p._romm_api,
        state=p._state,
        metadata_cache=p._metadata_cache,
        loop=asyncio.get_event_loop(),
        logger=decky.logger,
        save_metadata_cache=p._save_metadata_cache,
        log_debug=p._log_debug,
    )
    p._metadata_service = metadata_service

    p._sync_service = LibraryService(
        romm_api=p._romm_api,
        steam_config=steam_config,
        state=p._state,
        settings=p.settings,
        metadata_cache=p._metadata_cache,
        loop=asyncio.get_event_loop(),
        logger=decky.logger,
        plugin_dir=decky.DECKY_PLUGIN_DIR,
        emit=decky.emit,
        save_state=p._save_state,
        save_settings_to_disk=p._save_settings_to_disk,
        log_debug=p._log_debug,
        metadata_service=metadata_service,
    )
    return p


@pytest.fixture(autouse=True)
async def _set_event_loop(plugin):
    """Ensure the sync_service loop matches the running event loop."""
    plugin._sync_service._loop = asyncio.get_event_loop()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_loop_with_executor(*return_values):
    """Return a mock loop whose run_in_executor returns values in sequence.

    Each call to run_in_executor returns the next value from return_values.
    If only one value is given it is returned for every call.
    """
    mock_loop = MagicMock()
    if len(return_values) == 1:
        mock_loop.run_in_executor = AsyncMock(return_value=return_values[0])
    else:
        mock_loop.run_in_executor = AsyncMock(side_effect=list(return_values))
    return mock_loop


def _make_loop_raising(exc):
    """Return a mock loop whose run_in_executor always raises exc."""
    mock_loop = MagicMock()
    mock_loop.run_in_executor = AsyncMock(side_effect=exc)
    return mock_loop


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# conftest.py already provides a `plugin` fixture wired with a LibraryService
# (plugin._sync_service).  We reuse it here — no separate fixture needed.


# ---------------------------------------------------------------------------
# TestGetCollections
# ---------------------------------------------------------------------------


class TestGetCollections:
    """Tests for LibraryService.get_collections()."""

    @pytest.mark.asyncio
    async def test_returns_user_and_franchise_collections(self, plugin):
        """Both user and franchise collections appear in the result."""
        user = [{"id": 1, "name": "My Faves", "rom_count": 3, "is_favorite": False}]
        franchise = [{"id": 101, "name": "Mario", "rom_count": 5, "is_favorite": False}]
        plugin._sync_service._loop = _make_loop_with_executor(user, franchise)

        result = await plugin._sync_service.get_collections()

        assert result["success"] is True
        collections = result["collections"]
        names = [c["name"] for c in collections]
        assert "My Faves" in names
        assert "Mario" in names

    @pytest.mark.asyncio
    async def test_user_collection_has_user_category(self, plugin):
        """Non-favorite user collections are categorised as 'user'."""
        user = [{"id": 1, "name": "RPGs", "rom_count": 2, "is_favorite": False}]
        franchise = []
        plugin._sync_service._loop = _make_loop_with_executor(user, franchise)

        result = await plugin._sync_service.get_collections()

        assert result["collections"][0]["category"] == "user"

    @pytest.mark.asyncio
    async def test_franchise_collection_has_franchise_category(self, plugin):
        """Franchise collections are categorised as 'franchise'."""
        user = []
        franchise = [{"id": 101, "name": "Zelda", "rom_count": 4, "is_favorite": False}]
        plugin._sync_service._loop = _make_loop_with_executor(user, franchise)

        result = await plugin._sync_service.get_collections()

        assert result["collections"][0]["category"] == "franchise"

    @pytest.mark.asyncio
    async def test_favorites_sorted_first(self, plugin):
        """Favorite user collections appear before regular user and franchise collections."""
        user = [
            {"id": 1, "name": "Adventure", "rom_count": 1, "is_favorite": False},
            {"id": 2, "name": "A Favorites", "rom_count": 2, "is_favorite": True},
        ]
        franchise = [{"id": 101, "name": "Metroid", "rom_count": 3, "is_favorite": False}]
        plugin._sync_service._loop = _make_loop_with_executor(user, franchise)

        result = await plugin._sync_service.get_collections()

        categories = [c["category"] for c in result["collections"]]
        # Favorites must come before user must come before franchise
        fav_idx = categories.index("favorites")
        user_idx = categories.index("user")
        franchise_idx = categories.index("franchise")
        assert fav_idx < user_idx < franchise_idx

    @pytest.mark.asyncio
    async def test_favorite_collection_has_favorites_category(self, plugin):
        """Collections with is_favorite=True are categorised as 'favorites'."""
        user = [{"id": 1, "name": "Top Picks", "rom_count": 5, "is_favorite": True}]
        franchise = []
        plugin._sync_service._loop = _make_loop_with_executor(user, franchise)

        result = await plugin._sync_service.get_collections()

        assert result["collections"][0]["category"] == "favorites"

    @pytest.mark.asyncio
    async def test_respects_enabled_settings(self, plugin):
        """sync_enabled reflects the enabled_collections setting."""
        user = [
            {"id": 1, "name": "RPGs", "rom_count": 2, "is_favorite": False},
            {"id": 2, "name": "Shooters", "rom_count": 3, "is_favorite": False},
        ]
        franchise = []
        plugin._sync_service._loop = _make_loop_with_executor(user, franchise)
        plugin._sync_service._settings["enabled_collections"] = {"1": True, "2": False}

        result = await plugin._sync_service.get_collections()

        by_id = {c["id"]: c for c in result["collections"]}
        assert by_id["1"]["sync_enabled"] is True
        assert by_id["2"]["sync_enabled"] is False

    @pytest.mark.asyncio
    async def test_defaults_to_disabled_when_no_settings(self, plugin):
        """When enabled_collections is absent all collections default to sync_enabled=False."""
        user = [{"id": 1, "name": "RPGs", "rom_count": 2, "is_favorite": False}]
        franchise = [{"id": 101, "name": "Zelda", "rom_count": 3}]
        plugin._sync_service._loop = _make_loop_with_executor(user, franchise)
        plugin._sync_service._settings.pop("enabled_collections", None)

        result = await plugin._sync_service.get_collections()

        for c in result["collections"]:
            assert c["sync_enabled"] is False

    @pytest.mark.asyncio
    async def test_api_error_returns_error_response(self, plugin):
        """When list_collections raises an exception the response has success=False."""
        plugin._sync_service._loop = _make_loop_raising(Exception("Connection refused"))

        result = await plugin._sync_service.get_collections()

        assert result["success"] is False
        assert "error_code" in result
        assert "message" in result

    @pytest.mark.asyncio
    async def test_empty_collections(self, plugin):
        """Both endpoints returning [] still yields success=True with empty list."""
        plugin._sync_service._loop = _make_loop_with_executor([], [])

        result = await plugin._sync_service.get_collections()

        assert result["success"] is True
        assert result["collections"] == []

    @pytest.mark.asyncio
    async def test_franchise_failure_still_returns_user_collections(self, plugin):
        """If only franchise fetch fails, user collections are still returned."""
        user = [{"id": 1, "name": "RPGs", "rom_count": 2, "is_favorite": False}]

        mock_loop = MagicMock()
        call_count = 0

        async def _executor(_executor_arg, fn, *args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return user
            raise Exception("Franchise endpoint unavailable")

        mock_loop.run_in_executor = AsyncMock(side_effect=_executor)
        plugin._sync_service._loop = mock_loop

        result = await plugin._sync_service.get_collections()

        assert result["success"] is True
        assert len(result["collections"]) == 1
        assert result["collections"][0]["name"] == "RPGs"

    @pytest.mark.asyncio
    async def test_rom_count_falls_back_to_rom_ids_length(self, plugin):
        """When rom_count is absent, len(rom_ids) is used."""
        user = [{"id": 1, "name": "RPGs", "rom_ids": [10, 20, 30], "is_favorite": False}]
        franchise = []
        plugin._sync_service._loop = _make_loop_with_executor(user, franchise)

        result = await plugin._sync_service.get_collections()

        assert result["collections"][0]["rom_count"] == 3

    @pytest.mark.asyncio
    async def test_collections_sorted_alphabetically_within_category(self, plugin):
        """Within a category, collections are sorted by name (case-insensitive)."""
        user = [
            {"id": 2, "name": "Zelda", "rom_count": 1, "is_favorite": False},
            {"id": 1, "name": "Metroid", "rom_count": 1, "is_favorite": False},
        ]
        franchise = []
        plugin._sync_service._loop = _make_loop_with_executor(user, franchise)

        result = await plugin._sync_service.get_collections()

        names = [c["name"] for c in result["collections"]]
        assert names == ["Metroid", "Zelda"]

    @pytest.mark.asyncio
    async def test_collection_id_is_string(self, plugin):
        """IDs are always returned as strings regardless of the API response type."""
        user = [{"id": 42, "name": "Favorites", "rom_count": 1, "is_favorite": False}]
        franchise = []
        plugin._sync_service._loop = _make_loop_with_executor(user, franchise)

        result = await plugin._sync_service.get_collections()

        assert result["collections"][0]["id"] == "42"


# ---------------------------------------------------------------------------
# TestSaveCollectionSync
# ---------------------------------------------------------------------------


class TestSaveCollectionSync:
    """Tests for LibraryService.save_collection_sync() — synchronous method."""

    def test_saves_enabled(self, plugin):
        """Enabling a collection stores True under its id."""
        plugin._sync_service.save_collection_sync("42", True)

        assert plugin._sync_service._settings["enabled_collections"]["42"] is True

    def test_saves_disabled(self, plugin):
        """Disabling a previously-enabled collection stores False."""
        plugin._sync_service._settings["enabled_collections"] = {"42": True}

        plugin._sync_service.save_collection_sync("42", False)

        assert plugin._sync_service._settings["enabled_collections"]["42"] is False

    def test_returns_success(self, plugin):
        result = plugin._sync_service.save_collection_sync("1", True)

        assert result == {"success": True}

    def test_string_id_stored_from_int(self, plugin):
        """Passing an integer id is coerced to a string key."""
        plugin._sync_service.save_collection_sync(99, True)

        assert "99" in plugin._sync_service._settings["enabled_collections"]
        assert plugin._sync_service._settings["enabled_collections"]["99"] is True

    def test_string_id_stored_from_base64(self, plugin):
        """Base64-style string ids are stored as-is."""
        b64_id = "dXNlcjoxMjM="
        plugin._sync_service.save_collection_sync(b64_id, True)

        assert plugin._sync_service._settings["enabled_collections"][b64_id] is True

    def test_creates_enabled_collections_key_if_absent(self, plugin):
        """enabled_collections is created if it does not exist in settings."""
        plugin._sync_service._settings.pop("enabled_collections", None)

        plugin._sync_service.save_collection_sync("7", True)

        assert plugin._sync_service._settings["enabled_collections"]["7"] is True

    def test_calls_save_settings(self, plugin):
        """save_settings_to_disk is called after updating the setting."""
        save_called = []
        plugin._sync_service._save_settings_to_disk = lambda: save_called.append(True)

        plugin._sync_service.save_collection_sync("1", True)

        assert save_called


# ---------------------------------------------------------------------------
# TestSetAllCollectionsSync
# ---------------------------------------------------------------------------


class TestSetAllCollectionsSync:
    """Tests for LibraryService.set_all_collections_sync()."""

    @pytest.mark.asyncio
    async def test_enable_all(self, plugin):
        """Calling with enabled=True marks all collections as enabled."""
        user = [
            {"id": 1, "name": "RPGs", "is_favorite": False},
            {"id": 2, "name": "Action", "is_favorite": False},
        ]
        franchise = [{"id": 101, "name": "Mario", "is_favorite": False}]
        plugin._sync_service._loop = _make_loop_with_executor(user, franchise)

        result = await plugin._sync_service.set_all_collections_sync(True)

        assert result["success"] is True
        ec = plugin._sync_service._settings["enabled_collections"]
        assert ec["1"] is True
        assert ec["2"] is True
        assert ec["101"] is True

    @pytest.mark.asyncio
    async def test_disable_all(self, plugin):
        """Calling with enabled=False marks all collections as disabled."""
        user = [{"id": 1, "name": "RPGs", "is_favorite": False}]
        franchise = [{"id": 101, "name": "Mario", "is_favorite": False}]
        plugin._sync_service._loop = _make_loop_with_executor(user, franchise)
        plugin._sync_service._settings["enabled_collections"] = {"1": True, "101": True}

        result = await plugin._sync_service.set_all_collections_sync(False)

        assert result["success"] is True
        ec = plugin._sync_service._settings["enabled_collections"]
        assert ec["1"] is False
        assert ec["101"] is False

    @pytest.mark.asyncio
    async def test_filter_by_franchise_category(self, plugin):
        """Passing category='franchise' only touches franchise collections."""
        user = [{"id": 1, "name": "RPGs", "is_favorite": False}]
        franchise = [{"id": 101, "name": "Mario", "is_favorite": False}]
        plugin._sync_service._loop = _make_loop_with_executor(user, franchise)
        plugin._sync_service._settings["enabled_collections"] = {}

        result = await plugin._sync_service.set_all_collections_sync(True, category="franchise")

        assert result["success"] is True
        ec = plugin._sync_service._settings["enabled_collections"]
        assert ec.get("101") is True
        assert "1" not in ec

    @pytest.mark.asyncio
    async def test_filter_by_user_category(self, plugin):
        """Passing category='user' only touches non-favorite user collections."""
        user = [{"id": 1, "name": "RPGs", "is_favorite": False}]
        franchise = [{"id": 101, "name": "Mario", "is_favorite": False}]
        plugin._sync_service._loop = _make_loop_with_executor(user, franchise)
        plugin._sync_service._settings["enabled_collections"] = {}

        result = await plugin._sync_service.set_all_collections_sync(True, category="user")

        assert result["success"] is True
        ec = plugin._sync_service._settings["enabled_collections"]
        assert ec.get("1") is True
        assert "101" not in ec

    @pytest.mark.asyncio
    async def test_filter_by_favorites_category(self, plugin):
        """Passing category='favorites' only touches is_favorite=True collections."""
        user = [
            {"id": 1, "name": "Top Picks", "is_favorite": True},
            {"id": 2, "name": "RPGs", "is_favorite": False},
        ]
        franchise = []
        plugin._sync_service._loop = _make_loop_with_executor(user, franchise)
        plugin._sync_service._settings["enabled_collections"] = {}

        result = await plugin._sync_service.set_all_collections_sync(True, category="favorites")

        assert result["success"] is True
        ec = plugin._sync_service._settings["enabled_collections"]
        assert ec.get("1") is True
        assert "2" not in ec

    @pytest.mark.asyncio
    async def test_api_error_returns_error_response(self, plugin):
        """When list_collections raises, the response has success=False."""
        plugin._sync_service._loop = _make_loop_raising(Exception("timeout"))

        result = await plugin._sync_service.set_all_collections_sync(True)

        assert result["success"] is False
        assert "error_code" in result

    @pytest.mark.asyncio
    async def test_franchise_failure_still_processes_user_collections(self, plugin):
        """If franchise fetch fails, user collections are still processed."""
        user = [{"id": 1, "name": "RPGs", "is_favorite": False}]

        mock_loop = MagicMock()
        call_count = 0

        async def _executor(_executor_arg, fn, *args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return user
            raise Exception("Franchise endpoint unavailable")

        mock_loop.run_in_executor = AsyncMock(side_effect=_executor)
        plugin._sync_service._loop = mock_loop

        result = await plugin._sync_service.set_all_collections_sync(True)

        assert result["success"] is True
        assert plugin._sync_service._settings["enabled_collections"]["1"] is True

    @pytest.mark.asyncio
    async def test_calls_save_settings(self, plugin):
        """save_settings_to_disk is called after updating collections."""
        user = [{"id": 1, "name": "RPGs", "is_favorite": False}]
        franchise = []
        plugin._sync_service._loop = _make_loop_with_executor(user, franchise)

        save_called = []
        plugin._sync_service._save_settings_to_disk = lambda: save_called.append(True)

        await plugin._sync_service.set_all_collections_sync(True)

        assert save_called

    @pytest.mark.asyncio
    async def test_enabled_param_coerced_to_bool(self, plugin):
        """Truthy/falsy values are coerced to bool."""
        user = [{"id": 1, "name": "RPGs", "is_favorite": False}]
        franchise = []
        plugin._sync_service._loop = _make_loop_with_executor(user, franchise)

        await plugin._sync_service.set_all_collections_sync(1)  # truthy int

        assert plugin._sync_service._settings["enabled_collections"]["1"] is True

    @pytest.mark.asyncio
    async def test_category_none_processes_all(self, plugin):
        """When category is None (default), all categories are processed."""
        user = [
            {"id": 1, "name": "Faves", "is_favorite": True},
            {"id": 2, "name": "RPGs", "is_favorite": False},
        ]
        franchise = [{"id": 101, "name": "Mario", "is_favorite": False}]
        plugin._sync_service._loop = _make_loop_with_executor(user, franchise)

        await plugin._sync_service.set_all_collections_sync(True, category=None)

        ec = plugin._sync_service._settings["enabled_collections"]
        assert ec["1"] is True
        assert ec["2"] is True
        assert ec["101"] is True


# ---------------------------------------------------------------------------
# TestGetCollectionsUnsupported / TestSetAllCollectionsSyncUnsupported
# ---------------------------------------------------------------------------


class TestGetCollectionsUnsupportedError:
    """Tests for RommUnsupportedError handling in get_collections()."""

    @pytest.mark.asyncio
    async def test_returns_unsupported_error_response(self, plugin):
        """When RommUnsupportedError is raised, returns a structured error."""
        plugin._sync_service._loop = _make_loop_raising(RommUnsupportedError("Collections", "4.7.0"))

        result = await plugin._sync_service.get_collections()

        assert result["success"] is False
        assert result["error_code"] == "unsupported_error"
        assert "4.7.0" in result["message"]


class TestSetAllCollectionsSyncUnsupportedError:
    """Tests for RommUnsupportedError handling in set_all_collections_sync()."""

    @pytest.mark.asyncio
    async def test_returns_unsupported_error_response(self, plugin):
        """When RommUnsupportedError is raised, returns a structured error."""
        plugin._sync_service._loop = _make_loop_raising(RommUnsupportedError("Collections", "4.7.0"))

        result = await plugin._sync_service.set_all_collections_sync(True)

        assert result["success"] is False
        assert result["error_code"] == "unsupported_error"
        assert "4.7.0" in result["message"]


# ---------------------------------------------------------------------------
# TestFetchCollectionRoms
# ---------------------------------------------------------------------------


class TestFetchCollectionRoms:
    """Tests for LibraryService._fetch_collection_roms()."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_collections_enabled(self, plugin):
        """When no collections are enabled, returns empty results immediately."""
        plugin._sync_service._settings["enabled_collections"] = {"1": False, "2": False}

        roms, memberships = await plugin._sync_service._fetch_collection_roms(set())

        assert roms == []
        assert memberships == {}

    @pytest.mark.asyncio
    async def test_returns_empty_when_enabled_collections_absent(self, plugin):
        """When enabled_collections key is absent, returns empty results."""
        plugin._sync_service._settings.pop("enabled_collections", None)

        roms, memberships = await plugin._sync_service._fetch_collection_roms(set())

        assert roms == []
        assert memberships == {}

    @pytest.mark.asyncio
    async def test_deduplicates_against_seen_ids(self, plugin):
        """ROMs already in seen_rom_ids are not added to collection_only_roms."""
        plugin._sync_service._settings["enabled_collections"] = {"1": True}
        user = [{"id": 1, "name": "My Collection", "is_virtual": False}]
        page = {
            "items": [
                {"id": 10, "name": "ROM A", "platform_name": "N64", "platform_slug": "n64"},
                {"id": 20, "name": "ROM B", "platform_name": "SNES", "platform_slug": "snes"},
            ]
        }
        plugin._sync_service._loop = _make_loop_with_executor(user, [], page)

        roms, memberships = await plugin._sync_service._fetch_collection_roms({10})

        # ROM A (id=10) was already seen, only ROM B is new
        assert len(roms) == 1
        assert roms[0]["id"] == 20
        # But both are tracked in memberships
        assert 10 in memberships["My Collection"]
        assert 20 in memberships["My Collection"]

    @pytest.mark.asyncio
    async def test_returns_all_rom_ids_in_memberships(self, plugin):
        """collection_memberships includes ALL rom_ids in the collection, not just new ones."""
        plugin._sync_service._settings["enabled_collections"] = {"1": True}
        user = [{"id": 1, "name": "Favorites", "is_virtual": False}]
        page = {
            "items": [
                {"id": 5, "name": "ROM A", "platform_name": "N64", "platform_slug": "n64"},
                {"id": 6, "name": "ROM B", "platform_name": "N64", "platform_slug": "n64"},
            ]
        }
        plugin._sync_service._loop = _make_loop_with_executor(user, [], page)

        roms, memberships = await plugin._sync_service._fetch_collection_roms(set())

        assert set(memberships["Favorites"]) == {5, 6}
        assert len(roms) == 2

    @pytest.mark.asyncio
    async def test_skips_disabled_collections(self, plugin):
        """Collections with enabled=False are not fetched."""
        plugin._sync_service._settings["enabled_collections"] = {"1": False, "2": True}
        user = [
            {"id": 1, "name": "Disabled", "is_virtual": False},
            {"id": 2, "name": "Enabled", "is_virtual": False},
        ]
        page = {"items": [{"id": 10, "name": "ROM A", "platform_name": "N64", "platform_slug": "n64"}]}
        # First executor call: list_collections, second: list_virtual_collections (franchise),
        # third: list_roms_by_collection for collection id=2
        plugin._sync_service._loop = _make_loop_with_executor(user, [], page)

        _roms, memberships = await plugin._sync_service._fetch_collection_roms(set())

        assert "Disabled" not in memberships
        assert "Enabled" in memberships

    @pytest.mark.asyncio
    async def test_strips_files_array_from_roms(self, plugin):
        """The files array is stripped from ROM dicts to save memory."""
        plugin._sync_service._settings["enabled_collections"] = {"1": True}
        user = [{"id": 1, "name": "My Collection", "is_virtual": False}]
        page = {
            "items": [
                {"id": 10, "name": "ROM A", "platform_name": "N64", "platform_slug": "n64", "files": ["f1", "f2"]},
            ]
        }
        plugin._sync_service._loop = _make_loop_with_executor(user, [], page)

        roms, _ = await plugin._sync_service._fetch_collection_roms(set())

        assert "files" not in roms[0]

    @pytest.mark.asyncio
    async def test_handles_unsupported_error_gracefully(self, plugin):
        """RommUnsupportedError is caught and empty results are returned."""
        plugin._sync_service._settings["enabled_collections"] = {"1": True}
        plugin._sync_service._loop = _make_loop_raising(RommUnsupportedError("Collections", "4.7.0"))

        roms, memberships = await plugin._sync_service._fetch_collection_roms(set())

        assert roms == []
        assert memberships == {}

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(self, plugin):
        """Generic API errors are caught and empty results are returned."""
        plugin._sync_service._settings["enabled_collections"] = {"1": True}
        plugin._sync_service._loop = _make_loop_raising(Exception("Connection refused"))

        roms, memberships = await plugin._sync_service._fetch_collection_roms(set())

        assert roms == []
        assert memberships == {}

    @pytest.mark.asyncio
    async def test_virtual_collection_uses_virtual_endpoint(self, plugin):
        """Virtual collections are fetched via list_roms_by_virtual_collection."""
        plugin._sync_service._settings["enabled_collections"] = {"mario": True}
        user = []
        franchise = [{"id": "mario", "name": "Mario", "is_virtual": True}]
        page = {"items": [{"id": 42, "name": "Super Mario", "platform_name": "NES", "platform_slug": "nes"}]}

        mock_loop = MagicMock()
        call_count = 0

        captured_calls: list = []

        async def _executor(_exec_arg, fn, *args):
            nonlocal call_count
            call_count += 1
            captured_calls.append((fn, args))
            if call_count == 1:
                return user
            if call_count == 2:
                return franchise
            return page

        mock_loop.run_in_executor = AsyncMock(side_effect=_executor)
        plugin._sync_service._loop = mock_loop

        roms, memberships = await plugin._sync_service._fetch_collection_roms(set())

        # The third call should use list_roms_by_virtual_collection
        third_fn = captured_calls[2][0]
        assert third_fn == plugin._sync_service._romm_api.list_roms_by_virtual_collection
        assert "Mario" in memberships
        assert roms[0]["id"] == 42
