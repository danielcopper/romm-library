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


# ---------------------------------------------------------------------------
# TestCollectionSyncEdgeCases
# ---------------------------------------------------------------------------


def _make_rom(rom_id, name, platform_name, platform_slug="gba"):
    """Build a minimal ROM dict as returned by the RomM API."""
    return {
        "id": rom_id,
        "name": name,
        "fs_name": f"{name}.zip",
        "platform_name": platform_name,
        "platform_slug": platform_slug,
    }


def _make_registry_entry(name, platform_name, app_id, platform_slug="gba"):
    """Build a minimal shortcut registry entry."""
    return {
        "app_id": app_id,
        "name": name,
        "fs_name": f"{name}.zip",
        "platform_name": platform_name,
        "platform_slug": platform_slug,
        "cover_path": "",
    }


def _page(items):
    """Wrap items in a paginated API response dict."""
    return {"items": items, "total": len(items)}


class TestCollectionSyncEdgeCases:
    """Edge-case tests for the merged platform + collection sync engine.

    Tests exercise _classify_roms() and _report_sync_results_io() directly,
    and use _fetch_collection_roms() for collection-fetch scenarios.
    """

    # ------------------------------------------------------------------
    # Scenario 1: Platform disabled, collection keeps game alive
    # ------------------------------------------------------------------

    def test_sc1_collection_keeps_rom_alive_when_platform_disabled(self, plugin):
        """ROM A stays because Favorites collection references it; ROM B becomes stale.

        Platform GBA is disabled between sync 1 and sync 2. The registry has
        both ROM A (id=1) and ROM B (id=2) from the previous sync. On sync 2,
        only ROM A appears in shortcuts_data (via collection). ROM B has no
        source and must be classified as stale.
        """
        svc = plugin._sync_service

        # Registry after first sync
        svc._state["shortcut_registry"] = {
            "1": _make_registry_entry("ROM A", "Game Boy Advance", app_id=1001),
            "2": _make_registry_entry("ROM B", "Game Boy Advance", app_id=1002),
        }

        # Second sync: GBA platform is disabled, Favorites collection keeps ROM A
        # shortcuts_data only contains ROM A (fetched via collection)
        shortcuts_data = [
            {
                "rom_id": 1,
                "name": "ROM A",
                "fs_name": "ROM A.zip",
                "platform_name": "Game Boy Advance",
                "platform_slug": "gba",
            }
        ]
        # GBA is not in fetched platform names (platform disabled)
        fetched_platform_names = set()

        new, _changed, unchanged_ids, stale, _disabled_count = svc._classify_roms(
            shortcuts_data, fetched_platform_names
        )

        assert 1 in unchanged_ids, "ROM A should be unchanged (collection keeps it alive)"
        assert 2 in stale, "ROM B should be stale (no source references it)"
        assert len(new) == 0
        assert len(_changed) == 0

    # ------------------------------------------------------------------
    # Scenario 2: Collection disabled, platform keeps game alive
    # ------------------------------------------------------------------

    def test_sc2_platform_keeps_rom_alive_when_collection_disabled(self, plugin):
        """ROM A stays (platform reference); ROM C becomes stale (collection-only, now disabled).

        Platform GBA enabled → ROM A stays. PSX not enabled and Favorites
        collection disabled → ROM C has no source and is stale.
        """
        svc = plugin._sync_service

        # Registry after first sync: ROM A (GBA via platform), ROM C (PSX via collection)
        svc._state["shortcut_registry"] = {
            "1": _make_registry_entry("ROM A", "Game Boy Advance", app_id=1001, platform_slug="gba"),
            "3": _make_registry_entry("ROM C", "PlayStation", app_id=1003, platform_slug="psx"),
        }

        # Second sync: Favorites disabled, GBA still enabled
        # shortcuts_data only contains ROM A from the GBA platform
        shortcuts_data = [
            {
                "rom_id": 1,
                "name": "ROM A",
                "fs_name": "ROM A.zip",
                "platform_name": "Game Boy Advance",
                "platform_slug": "gba",
            }
        ]
        fetched_platform_names = {"Game Boy Advance"}

        new, _changed, unchanged_ids, stale, disabled_count = svc._classify_roms(shortcuts_data, fetched_platform_names)

        assert 1 in unchanged_ids, "ROM A should be unchanged (platform still enabled)"
        assert 3 in stale, "ROM C should be stale (collection disabled, PSX not enabled)"
        assert len(new) == 0
        # disabled_count: ROM C's platform (PlayStation) is NOT in fetched_platform_names
        assert disabled_count == 1

    # ------------------------------------------------------------------
    # Scenario 3: Game in multiple collections, one disabled
    # ------------------------------------------------------------------

    def test_sc3_rom_stays_alive_when_one_of_two_collections_disabled(self, plugin):
        """ROM A stays because RPG collection still references it even after Favorites is disabled."""
        svc = plugin._sync_service

        svc._state["shortcut_registry"] = {
            "1": _make_registry_entry("ROM A", "Game Boy Advance", app_id=1001),
        }

        # ROM A still appears in shortcuts_data (RPG collection enabled)
        shortcuts_data = [
            {
                "rom_id": 1,
                "name": "ROM A",
                "fs_name": "ROM A.zip",
                "platform_name": "Game Boy Advance",
                "platform_slug": "gba",
            }
        ]
        fetched_platform_names = set()

        _new, _changed, unchanged_ids, stale, _disabled_count = svc._classify_roms(
            shortcuts_data, fetched_platform_names
        )

        assert 1 in unchanged_ids, "ROM A should stay alive via RPG collection"
        assert len(stale) == 0

    # ------------------------------------------------------------------
    # Scenario 4: Collection-only game (no platform enabled)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_sc4_collection_only_rom_is_synced_without_platform(self, plugin):
        """ROM A is synced via collection fetch when its platform is not enabled."""
        svc = plugin._sync_service
        svc._settings["enabled_platforms"] = {}  # No platforms enabled
        svc._settings["enabled_collections"] = {"10": True}

        # API mocks: no enabled platforms → no platform ROMs
        # list_collections → one collection; list_roms_by_collection → ROM A
        rom_a = {
            "id": 1,
            "name": "ROM A",
            "fs_name": "ROM A.zip",
            "platform_name": "Game Boy Advance",
            "platform_slug": "gba",
        }
        user_collections = [{"id": 10, "name": "Favorites", "is_virtual": False}]
        franchise_collections: list = []

        mock_loop = MagicMock()
        call_num = 0

        async def _executor(_exec, fn, *args):
            nonlocal call_num
            call_num += 1
            if call_num == 1:
                # list_platforms → empty (but this is called by _fetch_enabled_platforms)
                return []
            if call_num == 2:
                # list_collections inside _fetch_collection_roms
                return user_collections
            if call_num == 3:
                # list_virtual_collections (franchise)
                return franchise_collections
            # list_roms_by_collection for collection id=10
            return _page([rom_a])

        mock_loop.run_in_executor = AsyncMock(side_effect=_executor)
        svc._loop = mock_loop

        # _fetch_and_prepare drives the whole flow
        all_roms, shortcuts_data, _platforms, collection_memberships, platform_rom_ids = await svc._fetch_and_prepare()

        assert len(all_roms) == 1
        assert all_roms[0]["id"] == 1
        assert len(shortcuts_data) == 1
        assert shortcuts_data[0]["rom_id"] == 1
        # ROM A came from collection, not platform
        assert 1 not in platform_rom_ids
        assert "Favorites" in collection_memberships
        assert 1 in collection_memberships["Favorites"]

    # ------------------------------------------------------------------
    # Scenario 5: collection_create_platform_groups = False (default)
    # ------------------------------------------------------------------

    def test_sc5_collection_rom_excluded_from_platform_groups_by_default(self, plugin):
        """With toggle OFF, collection-only ROM B (PSX) is not included in platform_app_ids for PSX."""
        svc = plugin._sync_service
        svc._settings["collection_create_platform_groups"] = False

        # ROM A (id=1) came via GBA platform; ROM B (id=2) came via collection only (PSX)
        svc._state["shortcut_registry"] = {
            "1": _make_registry_entry("ROM A", "Game Boy Advance", app_id=1001, platform_slug="gba"),
            "2": _make_registry_entry("ROM B", "PlayStation", app_id=1002, platform_slug="psx"),
        }

        # platform_rom_ids only contains ROM A (from platform fetch)
        svc._pending_platform_rom_ids = {1}
        svc._pending_collection_memberships = {"Favorites": [1, 2]}
        svc._pending_sync = {
            1: {
                "name": "ROM A",
                "platform_name": "Game Boy Advance",
                "platform_slug": "gba",
                "cover_path": "",
            },
            2: {
                "name": "ROM B",
                "platform_name": "PlayStation",
                "platform_slug": "psx",
                "cover_path": "",
            },
        }

        platform_app_ids, _romm_collection_app_ids = svc._report_sync_results_io({}, [])

        assert "Game Boy Advance" in platform_app_ids
        assert 1001 in platform_app_ids["Game Boy Advance"]
        # PSX platform group should NOT be created because ROM B is collection-only
        assert "PlayStation" not in platform_app_ids

    # ------------------------------------------------------------------
    # Scenario 6: collection_create_platform_groups = True
    # ------------------------------------------------------------------

    def test_sc6_collection_rom_included_in_platform_groups_when_toggle_on(self, plugin):
        """With toggle ON, collection-only ROM B (PSX) IS included in platform_app_ids for PSX."""
        svc = plugin._sync_service
        svc._settings["collection_create_platform_groups"] = True

        svc._state["shortcut_registry"] = {
            "1": _make_registry_entry("ROM A", "Game Boy Advance", app_id=1001, platform_slug="gba"),
            "2": _make_registry_entry("ROM B", "PlayStation", app_id=1002, platform_slug="psx"),
        }

        svc._pending_platform_rom_ids = {1}
        svc._pending_collection_memberships = {"Favorites": [1, 2]}
        svc._pending_sync = {
            1: {
                "name": "ROM A",
                "platform_name": "Game Boy Advance",
                "platform_slug": "gba",
                "cover_path": "",
            },
            2: {
                "name": "ROM B",
                "platform_name": "PlayStation",
                "platform_slug": "psx",
                "cover_path": "",
            },
        }

        platform_app_ids, _romm_collection_app_ids = svc._report_sync_results_io({}, [])

        assert "Game Boy Advance" in platform_app_ids
        assert 1001 in platform_app_ids["Game Boy Advance"]
        # PSX platform group SHOULD exist because toggle is on
        assert "PlayStation" in platform_app_ids
        assert 1002 in platform_app_ids["PlayStation"]

    # ------------------------------------------------------------------
    # Scenario 5b/6b: Platform groups toggle in _should_include_in_platform_collection
    # These test the shared helper that both sync_apply_delta and
    # _report_sync_results_io use — the bug was that sync_apply_delta
    # didn't apply the toggle at all.
    # ------------------------------------------------------------------

    def test_sc5b_should_include_helper_excludes_collection_only_rom(self, plugin):
        """Helper returns False for collection-only ROM when toggle is OFF."""
        svc = plugin._sync_service
        svc._settings["collection_create_platform_groups"] = False
        platform_rom_ids = {1, 2}  # ROM 3 is collection-only
        assert svc._should_include_in_platform_collection(1, platform_rom_ids) is True
        assert svc._should_include_in_platform_collection(3, platform_rom_ids) is False

    def test_sc5b_should_include_helper_includes_all_when_toggle_on(self, plugin):
        """Helper returns True for all ROMs when toggle is ON."""
        svc = plugin._sync_service
        svc._settings["collection_create_platform_groups"] = True
        platform_rom_ids = {1, 2}
        assert svc._should_include_in_platform_collection(1, platform_rom_ids) is True
        assert svc._should_include_in_platform_collection(3, platform_rom_ids) is True

    def test_sc5b_should_include_helper_includes_all_when_no_platform_tracking(self, plugin):
        """Helper returns True when platform_rom_ids is empty (backwards compat)."""
        svc = plugin._sync_service
        svc._settings["collection_create_platform_groups"] = False
        assert svc._should_include_in_platform_collection(1, set()) is True

    def test_sc5c_build_collection_app_ids_excludes_collection_only_roms(self, plugin):
        """_build_collection_app_ids respects the toggle.

        Platform collection mapping is built from the full registry in report_sync_results.
        collection-only ROMs must be excluded when the toggle is OFF.
        """
        svc = plugin._sync_service
        svc._settings["collection_create_platform_groups"] = False
        svc._settings["enabled_collections"] = {"3": True}

        # Registry: ROM 1 from platform, ROM 2 from collection only
        registry = {
            "1": _make_registry_entry("ROM A", "Game Boy Advance", app_id=1001, platform_slug="gba"),
            "2": _make_registry_entry("ROM B", "PlayStation", app_id=1002, platform_slug="psx"),
        }
        platform_rom_ids = {1}  # Only ROM 1 from platform

        platform_app_ids, _ = svc._build_collection_app_ids(registry, platform_rom_ids, {"Favorites": [1, 2]})

        assert "Game Boy Advance" in platform_app_ids
        assert 1001 in platform_app_ids["Game Boy Advance"]
        assert "PlayStation" not in platform_app_ids, "PSX should be excluded (collection-only, toggle OFF)"

    def test_sc6c_build_collection_app_ids_includes_all_when_toggle_on(self, plugin):
        """Same as sc5c but with toggle ON — PSX should be included."""
        svc = plugin._sync_service
        svc._settings["collection_create_platform_groups"] = True

        registry = {
            "1": _make_registry_entry("ROM A", "Game Boy Advance", app_id=1001, platform_slug="gba"),
            "2": _make_registry_entry("ROM B", "PlayStation", app_id=1002, platform_slug="psx"),
        }
        platform_rom_ids = {1}

        platform_app_ids, _ = svc._build_collection_app_ids(registry, platform_rom_ids, {})

        assert "Game Boy Advance" in platform_app_ids
        assert "PlayStation" in platform_app_ids, "PSX should be included (toggle ON)"

    # ------------------------------------------------------------------
    # Scenario 7: Deduplication — ROM in both platform and collection
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_sc7_rom_in_platform_and_collection_appears_once(self, plugin):
        """ROM A fetched from GBA platform is not duplicated when Favorites collection also has it."""
        svc = plugin._sync_service
        svc._settings["enabled_platforms"] = {"5": True}
        svc._settings["enabled_collections"] = {"10": True}

        rom_a = {
            "id": 1,
            "name": "ROM A",
            "fs_name": "ROM A.zip",
            "platform_name": "Game Boy Advance",
            "platform_slug": "gba",
        }
        platform = {"id": 5, "name": "Game Boy Advance", "slug": "gba", "rom_count": 1}
        user_collections = [{"id": 10, "name": "Favorites", "is_virtual": False}]

        mock_loop = MagicMock()
        call_num = 0

        async def _executor(_exec, fn, *args):
            nonlocal call_num
            call_num += 1
            if call_num == 1:
                # list_platforms
                return [platform]
            if call_num == 2:
                # list_roms for GBA (paginated)
                return _page([rom_a])
            if call_num == 3:
                # list_collections inside _fetch_collection_roms
                return user_collections
            if call_num == 4:
                # list_virtual_collections (franchise)
                return []
            # list_roms_by_collection for Favorites — ROM A already seen
            return _page([rom_a])

        mock_loop.run_in_executor = AsyncMock(side_effect=_executor)
        svc._loop = mock_loop

        _all_roms, shortcuts_data, _platforms, collection_memberships, platform_rom_ids = await svc._fetch_and_prepare()

        # ROM A should appear exactly once despite being in both platform and collection
        rom_ids_in_shortcuts = [sd["rom_id"] for sd in shortcuts_data]
        assert rom_ids_in_shortcuts.count(1) == 1, "ROM A must not be duplicated"

        # ROM A is in platform_rom_ids (fetched from platform)
        assert 1 in platform_rom_ids

        # ROM A must be in the Favorites collection membership
        assert "Favorites" in collection_memberships
        assert 1 in collection_memberships["Favorites"]

    def test_sc7_rom_appears_in_both_platform_and_collection_app_ids(self, plugin):
        """ROM A (in both GBA platform and Favorites collection) appears in both platform_app_ids
        and romm_collection_app_ids after _report_sync_results_io."""
        svc = plugin._sync_service
        svc._settings["collection_create_platform_groups"] = False

        svc._state["shortcut_registry"] = {
            "1": _make_registry_entry("ROM A", "Game Boy Advance", app_id=1001, platform_slug="gba"),
        }

        # ROM A came from platform
        svc._pending_platform_rom_ids = {1}
        svc._pending_collection_memberships = {"Favorites": [1]}
        svc._pending_sync = {}

        platform_app_ids, romm_collection_app_ids = svc._report_sync_results_io({}, [])

        # Platform group for GBA exists (ROM A is a platform ROM)
        assert "Game Boy Advance" in platform_app_ids
        assert 1001 in platform_app_ids["Game Boy Advance"]

        # Favorites collection app_ids also contains ROM A
        assert "Favorites" in romm_collection_app_ids
        assert 1001 in romm_collection_app_ids["Favorites"]

    # ------------------------------------------------------------------
    # Scenario 8: All sources removed — game gets stale
    # ------------------------------------------------------------------

    def test_sc8_rom_becomes_stale_when_no_source_references_it(self, plugin):
        """ROM A classified as stale when neither platform nor collection brings it in."""
        svc = plugin._sync_service

        svc._state["shortcut_registry"] = {
            "1": _make_registry_entry("ROM A", "Game Boy Advance", app_id=1001),
        }

        # Empty shortcuts_data — no ROM was fetched from any source
        shortcuts_data: list = []
        fetched_platform_names: set = set()

        new, changed, unchanged_ids, stale, _disabled_count = svc._classify_roms(shortcuts_data, fetched_platform_names)

        assert 1 in stale
        assert len(new) == 0
        assert len(changed) == 0
        assert len(unchanged_ids) == 0

    # ------------------------------------------------------------------
    # Scenario 9: Empty collection
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_sc9_empty_collection_does_not_error(self, plugin):
        """An enabled collection with no ROMs causes no errors and returns empty results."""
        svc = plugin._sync_service
        svc._settings["enabled_collections"] = {"10": True}

        user_collections = [{"id": 10, "name": "Empty", "is_virtual": False}]

        mock_loop = MagicMock()
        call_num = 0

        async def _executor(_exec, fn, *args):
            nonlocal call_num
            call_num += 1
            if call_num == 1:
                return user_collections
            if call_num == 2:
                return []  # no franchise collections
            # list_roms_by_collection returns an empty page
            return _page([])

        mock_loop.run_in_executor = AsyncMock(side_effect=_executor)
        svc._loop = mock_loop

        roms, memberships = await svc._fetch_collection_roms(set())

        assert roms == []
        # Empty collection produces no membership entry (no rom_ids collected)
        assert "Empty" not in memberships

    # ------------------------------------------------------------------
    # Scenario 10: Collection API failure is non-fatal
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_sc10_collection_api_failure_does_not_crash_sync(self, plugin):
        """When the collection API fails, sync continues with platform ROMs only."""
        svc = plugin._sync_service
        svc._settings["enabled_platforms"] = {"5": True}
        svc._settings["enabled_collections"] = {"10": True}

        rom_a = {
            "id": 1,
            "name": "ROM A",
            "fs_name": "ROM A.zip",
            "platform_name": "Game Boy Advance",
            "platform_slug": "gba",
        }
        platform = {"id": 5, "name": "Game Boy Advance", "slug": "gba", "rom_count": 1}

        mock_loop = MagicMock()
        call_num = 0

        async def _executor(_exec, fn, *args):
            nonlocal call_num
            call_num += 1
            if call_num == 1:
                # list_platforms
                return [platform]
            if call_num == 2:
                # list_roms for GBA
                return _page([rom_a])
            # All subsequent calls (list_collections, etc.) raise
            raise Exception("Collection API unavailable")

        mock_loop.run_in_executor = AsyncMock(side_effect=_executor)
        svc._loop = mock_loop

        # Should not raise; collection errors are caught and logged as warnings
        (
            all_roms,
            _shortcuts_data,
            _platforms,
            collection_memberships,
            _platform_rom_ids,
        ) = await svc._fetch_and_prepare()

        # Platform ROM was still fetched
        assert len(all_roms) == 1
        assert all_roms[0]["id"] == 1
        # No collection memberships because the fetch failed
        assert collection_memberships == {}

    # ------------------------------------------------------------------
    # Additional edge cases for _report_sync_results_io
    # ------------------------------------------------------------------

    def test_report_sync_clears_pending_state(self, plugin):
        """_report_sync_results_io clears pending_sync, pending_collection_memberships,
        and pending_platform_rom_ids after completion."""
        svc = plugin._sync_service

        svc._state["shortcut_registry"] = {}
        svc._pending_sync = {1: {"name": "ROM A", "platform_name": "GBA", "cover_path": ""}}
        svc._pending_collection_memberships = {"Favorites": [1]}
        svc._pending_platform_rom_ids = {1}

        svc._report_sync_results_io({}, [])

        assert svc._pending_sync == {}
        assert svc._pending_collection_memberships == {}
        assert svc._pending_platform_rom_ids == set()

    def test_report_sync_collection_app_ids_empty_when_no_memberships(self, plugin):
        """romm_collection_app_ids is empty when no collection memberships are set."""
        svc = plugin._sync_service

        svc._state["shortcut_registry"] = {
            "1": _make_registry_entry("ROM A", "GBA", app_id=1001),
        }
        svc._pending_platform_rom_ids = {1}
        svc._pending_collection_memberships = {}
        svc._pending_sync = {}

        _platform_app_ids, romm_collection_app_ids = svc._report_sync_results_io({}, [])

        assert romm_collection_app_ids == {}

    def test_report_sync_collection_app_ids_excludes_missing_registry_entries(self, plugin):
        """romm_collection_app_ids skips rom_ids that have no registry entry."""
        svc = plugin._sync_service

        # Only ROM id=1 is in the registry; ROM id=99 is referenced in memberships but missing
        svc._state["shortcut_registry"] = {
            "1": _make_registry_entry("ROM A", "GBA", app_id=1001),
        }
        svc._pending_platform_rom_ids = {1}
        svc._pending_collection_memberships = {"Favorites": [1, 99]}
        svc._pending_sync = {}

        _platform_app_ids, romm_collection_app_ids = svc._report_sync_results_io({}, [])

        assert "Favorites" in romm_collection_app_ids
        assert 1001 in romm_collection_app_ids["Favorites"]
        # ROM 99 has no registry entry, so its app_id is not included
        assert len(romm_collection_app_ids["Favorites"]) == 1

    def test_report_sync_platform_groups_include_newly_added_roms(self, plugin):
        """ROMs added in this sync (via rom_id_to_app_id) appear in platform_app_ids."""
        svc = plugin._sync_service
        svc._settings["collection_create_platform_groups"] = False

        # Registry is initially empty; the sync adds ROM A
        svc._state["shortcut_registry"] = {}
        svc._pending_platform_rom_ids = {1}
        svc._pending_collection_memberships = {}
        svc._pending_sync = {
            1: {
                "name": "ROM A",
                "platform_name": "Game Boy Advance",
                "platform_slug": "gba",
                "cover_path": "",
                "fs_name": "ROM A.zip",
            }
        }

        platform_app_ids, _romm = svc._report_sync_results_io({"1": 1001}, [])

        assert "Game Boy Advance" in platform_app_ids
        assert 1001 in platform_app_ids["Game Boy Advance"]

    def test_classify_roms_new_when_not_in_registry(self, plugin):
        """ROMs not present in the registry at all are classified as new."""
        svc = plugin._sync_service
        svc._state["shortcut_registry"] = {}

        shortcuts_data = [
            {
                "rom_id": 1,
                "name": "ROM A",
                "fs_name": "ROM A.zip",
                "platform_name": "GBA",
                "platform_slug": "gba",
            }
        ]

        new, changed, unchanged_ids, stale, _disabled_count = svc._classify_roms(shortcuts_data, {"GBA"})

        assert len(new) == 1
        assert new[0]["rom_id"] == 1
        assert len(changed) == 0
        assert len(unchanged_ids) == 0
        assert len(stale) == 0

    def test_classify_roms_changed_when_name_differs(self, plugin):
        """ROMs whose name changed since last sync are classified as changed."""
        svc = plugin._sync_service
        svc._state["shortcut_registry"] = {
            "1": _make_registry_entry("Old Name", "GBA", app_id=1001),
        }

        shortcuts_data = [
            {
                "rom_id": 1,
                "name": "New Name",  # name changed
                "fs_name": "Old Name.zip",
                "platform_name": "GBA",
                "platform_slug": "gba",
            }
        ]

        new, changed, unchanged_ids, _stale, _disabled_count = svc._classify_roms(shortcuts_data, {"GBA"})

        assert len(changed) == 1
        assert changed[0]["rom_id"] == 1
        assert changed[0]["existing_app_id"] == 1001
        assert len(new) == 0
        assert len(unchanged_ids) == 0
