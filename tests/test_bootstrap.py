"""Tests for the bootstrap composition root."""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

from adapters.persistence import PersistenceAdapter
from adapters.romm.http import RommHttpAdapter
from adapters.romm.version_router import VersionRouter
from adapters.steam_config import SteamConfigAdapter
from bootstrap import WiringConfig, bootstrap, wire_services
from services.achievements import AchievementsService
from services.downloads import DownloadService
from services.firmware import FirmwareService
from services.library import LibraryService
from services.metadata import MetadataService
from services.playtime import PlaytimeService
from services.saves import SaveService
from services.steamgrid import SteamGridService


class TestBootstrap:
    def test_returns_persistence_adapter(self, tmp_path):
        result = bootstrap(
            settings_dir=str(tmp_path / "settings"),
            runtime_dir=str(tmp_path / "runtime"),
            plugin_dir=str(tmp_path / "plugin"),
            user_home=str(tmp_path / "home"),
            logger=logging.getLogger("test"),
            settings={},
        )
        assert "persistence" in result
        assert isinstance(result["persistence"], PersistenceAdapter)

    def test_returns_http_adapter(self, tmp_path):
        result = bootstrap(
            settings_dir=str(tmp_path / "settings"),
            runtime_dir=str(tmp_path / "runtime"),
            plugin_dir=str(tmp_path / "plugin"),
            user_home=str(tmp_path / "home"),
            logger=logging.getLogger("test"),
            settings={},
        )
        assert "http_adapter" in result
        assert isinstance(result["http_adapter"], RommHttpAdapter)

    def test_http_adapter_shares_settings_reference(self, tmp_path):
        settings = {"romm_url": "http://example.com"}
        result = bootstrap(
            settings_dir=str(tmp_path / "settings"),
            runtime_dir=str(tmp_path / "runtime"),
            plugin_dir=str(tmp_path / "plugin"),
            user_home=str(tmp_path / "home"),
            logger=logging.getLogger("test"),
            settings=settings,
        )
        # Mutate original — client should see the change
        settings["romm_url"] = "http://changed.com"
        assert result["http_adapter"]._settings["romm_url"] == "http://changed.com"

    def test_persistence_has_correct_paths(self, tmp_path):
        settings_dir = str(tmp_path / "s")
        runtime_dir = str(tmp_path / "r")
        result = bootstrap(
            settings_dir=settings_dir,
            runtime_dir=runtime_dir,
            plugin_dir=str(tmp_path / "p"),
            user_home=str(tmp_path / "home"),
            logger=logging.getLogger("test"),
            settings={},
        )
        assert result["persistence"]._settings_dir == settings_dir
        assert result["persistence"]._runtime_dir == runtime_dir

    def test_returns_save_api_and_version_router(self, tmp_path):
        result = bootstrap(
            settings_dir=str(tmp_path / "settings"),
            runtime_dir=str(tmp_path / "runtime"),
            plugin_dir=str(tmp_path / "plugin"),
            user_home=str(tmp_path / "home"),
            logger=logging.getLogger("test"),
            settings={},
        )
        assert "save_api" in result
        assert "version_router" in result
        assert isinstance(result["version_router"], VersionRouter)
        # save_api is the same object as version_router
        assert result["save_api"] is result["version_router"]

    def test_returns_steam_config(self, tmp_path):
        result = bootstrap(
            settings_dir=str(tmp_path / "settings"),
            runtime_dir=str(tmp_path / "runtime"),
            plugin_dir=str(tmp_path / "plugin"),
            user_home=str(tmp_path / "home"),
            logger=logging.getLogger("test"),
            settings={},
        )
        assert "steam_config" in result
        assert isinstance(result["steam_config"], SteamConfigAdapter)


class TestWireServices:
    def _make_deps(self, tmp_path):
        logger = logging.getLogger("test_wire")
        settings = {}
        http_adapter = MagicMock(spec=RommHttpAdapter)
        steam_config = SteamConfigAdapter(user_home=str(tmp_path), logger=logger)
        save_api = MagicMock(spec=VersionRouter)
        state = {
            "shortcut_registry": {},
            "installed_roms": {},
            "last_sync": None,
            "sync_stats": {},
            "downloaded_bios": {},
        }
        return {
            "save_api": save_api,
            "http_adapter": http_adapter,
            "steam_config": steam_config,
            "state": state,
            "settings": settings,
            "metadata_cache": {},
            "save_sync_state": {"saves": {}, "playtime": {}, "settings": {}},
            "loop": asyncio.new_event_loop(),
            "logger": logger,
            "plugin_dir": str(tmp_path / "plugin"),
            "runtime_dir": str(tmp_path / "runtime"),
            "emit": AsyncMock(),
            "get_saves_path": MagicMock(return_value=str(tmp_path / "saves")),
            "save_state": MagicMock(),
            "save_settings_to_disk": MagicMock(),
            "save_metadata_cache": MagicMock(),
            "log_debug": MagicMock(),
        }

    def test_returns_all_services(self, tmp_path):
        deps = self._make_deps(tmp_path)
        result = wire_services(WiringConfig(**deps))
        assert isinstance(result["save_sync_service"], SaveService)
        assert isinstance(result["playtime_service"], PlaytimeService)
        assert isinstance(result["sync_service"], LibraryService)
        assert isinstance(result["download_service"], DownloadService)
        assert isinstance(result["firmware_service"], FirmwareService)
        assert isinstance(result["sgdb_service"], SteamGridService)
        assert isinstance(result["metadata_service"], MetadataService)
        assert isinstance(result["achievements_service"], AchievementsService)
        deps["loop"].close()

    def test_services_share_state_reference(self, tmp_path):
        deps = self._make_deps(tmp_path)
        result = wire_services(WiringConfig(**deps))
        # download_service and sync_service should share the same state dict
        assert result["download_service"]._state is deps["state"]
        assert result["sync_service"]._state is deps["state"]
        deps["loop"].close()

    def test_returns_nine_services(self, tmp_path):
        deps = self._make_deps(tmp_path)
        result = wire_services(WiringConfig(**deps))
        assert len(result) == 9
        assert "migration_service" in result
        deps["loop"].close()
