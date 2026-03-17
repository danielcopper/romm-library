"""Composition root — wires adapters and services for the plugin.

Called from ``Plugin._main()`` to create adapter instances with
the correct Decky paths and logger.  Returns a dict so that
``_main()`` can assign them to the plugin's lazy-property backing
attributes (bypassing auto-creation from ``self.settings``).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from adapters.persistence import PersistenceAdapter
from adapters.romm.api_router import ApiRouter
from adapters.romm.http import RommHttpAdapter
from adapters.romm.version_router import VersionRouter
from adapters.steam_config import SteamConfigAdapter
from services.achievements import AchievementsService
from services.downloads import DownloadService
from services.firmware import FirmwareService
from services.library import LibraryService
from services.metadata import MetadataService
from services.migration import MigrationService
from services.playtime import PlaytimeService
from services.protocols import HttpAdapter, RommApiProtocol
from services.protocols import SteamConfigAdapter as SteamConfigProtocol
from services.saves import SaveService
from services.steamgrid import SteamGridService


@dataclass
class WiringConfig:
    """Configuration bundle for wire_services — groups the 17 parameters
    into a single object to keep the composition root readable."""

    # Adapters
    save_api: Any
    http_adapter: HttpAdapter
    romm_api: RommApiProtocol
    steam_config: SteamConfigProtocol

    # State (live dict refs)
    state: dict
    settings: dict
    metadata_cache: dict
    save_sync_state: dict

    # Runtime
    loop: asyncio.AbstractEventLoop
    logger: logging.Logger
    plugin_dir: str
    runtime_dir: str
    emit: Any

    # Callbacks
    get_saves_path: Callable
    save_state: Callable
    save_settings_to_disk: Callable
    save_metadata_cache: Callable
    log_debug: Callable


def bootstrap(
    *,
    settings_dir: str,
    runtime_dir: str,
    plugin_dir: str,
    user_home: str,
    logger: logging.Logger,
    settings: dict,
) -> dict:
    """Create and return all adapters.

    Parameters
    ----------
    settings_dir:
        ``decky.DECKY_PLUGIN_SETTINGS_DIR``
    runtime_dir:
        ``decky.DECKY_PLUGIN_RUNTIME_DIR``
    plugin_dir:
        ``decky.DECKY_PLUGIN_DIR``
    logger:
        ``decky.logger``
    settings:
        The live settings dict (passed by reference to ``RommHttpAdapter``).

    Returns
    -------
    dict with keys ``persistence``, ``http_adapter``, and ``wire_services``
    (a factory callable for deferred service creation).
    """
    persistence = PersistenceAdapter(settings_dir, runtime_dir, logger)
    http_adapter = RommHttpAdapter(settings, plugin_dir, logger)
    version_router = VersionRouter(http_adapter)
    romm_api = ApiRouter(http_adapter)
    steam_config = SteamConfigAdapter(user_home=user_home, logger=logger)

    return {
        "persistence": persistence,
        "http_adapter": http_adapter,
        "save_api": version_router,
        "version_router": version_router,
        "romm_api": romm_api,
        "steam_config": steam_config,
    }


def wire_services(cfg: WiringConfig) -> dict:
    """Create service instances after plugin state is initialised.

    Called from ``Plugin._main()`` after save-sync state is populated
    so that services receive live references to the fully-populated
    state dicts.

    Returns
    -------
    dict with keys ``save_sync_service``, ``playtime_service``,
    ``sync_service``, ``download_service``, and ``firmware_service``.
    """
    save_sync_service = SaveService(
        save_api=cfg.save_api,
        with_retry=cfg.http_adapter.with_retry,
        is_retryable=cfg.http_adapter.is_retryable,
        state=cfg.state,
        save_sync_state=cfg.save_sync_state,
        loop=cfg.loop,
        logger=cfg.logger,
        runtime_dir=cfg.runtime_dir,
        get_saves_path=cfg.get_saves_path,
    )

    playtime_service = PlaytimeService(
        save_api=cfg.save_api,
        with_retry=cfg.http_adapter.with_retry,
        is_retryable=cfg.http_adapter.is_retryable,
        save_sync_state=cfg.save_sync_state,
        loop=cfg.loop,
        logger=cfg.logger,
        save_state=save_sync_service.save_state,
    )

    metadata_service = MetadataService(
        romm_api=cfg.romm_api,
        state=cfg.state,
        metadata_cache=cfg.metadata_cache,
        loop=cfg.loop,
        logger=cfg.logger,
        save_metadata_cache=cfg.save_metadata_cache,
        log_debug=cfg.log_debug,
    )

    sync_service = LibraryService(
        http_adapter=cfg.http_adapter,
        steam_config=cfg.steam_config,
        state=cfg.state,
        settings=cfg.settings,
        metadata_cache=cfg.metadata_cache,
        loop=cfg.loop,
        logger=cfg.logger,
        plugin_dir=cfg.plugin_dir,
        emit=cfg.emit,
        save_state=cfg.save_state,
        save_settings_to_disk=cfg.save_settings_to_disk,
        log_debug=cfg.log_debug,
        metadata_service=metadata_service,
    )

    download_service = DownloadService(
        romm_api=cfg.romm_api,
        resolve_system=cfg.http_adapter.resolve_system,
        state=cfg.state,
        save_sync_state=cfg.save_sync_state,
        loop=cfg.loop,
        logger=cfg.logger,
        runtime_dir=cfg.runtime_dir,
        emit=cfg.emit,
        save_state=cfg.save_state,
        save_save_sync_state=save_sync_service.save_state,
    )

    firmware_service = FirmwareService(
        romm_api=cfg.romm_api,
        state=cfg.state,
        loop=cfg.loop,
        logger=cfg.logger,
        plugin_dir=cfg.plugin_dir,
        save_state=cfg.save_state,
    )

    sgdb_service = SteamGridService(
        romm_api=cfg.romm_api,
        steam_config=cfg.steam_config,
        state=cfg.state,
        settings=cfg.settings,
        loop=cfg.loop,
        logger=cfg.logger,
        runtime_dir=cfg.runtime_dir,
        save_state=cfg.save_state,
        save_settings_to_disk=cfg.save_settings_to_disk,
        pending_sync=sync_service.pending_sync,
    )

    achievements_service = AchievementsService(
        romm_api=cfg.romm_api,
        state=cfg.state,
        loop=cfg.loop,
        logger=cfg.logger,
        log_debug=cfg.log_debug,
    )

    migration_service = MigrationService(
        state=cfg.state,
        loop=cfg.loop,
        logger=cfg.logger,
        save_state=cfg.save_state,
        emit=cfg.emit,
        firmware_service_bios_files_index=firmware_service.bios_files_index,
    )

    return {
        "save_sync_service": save_sync_service,
        "playtime_service": playtime_service,
        "sync_service": sync_service,
        "download_service": download_service,
        "firmware_service": firmware_service,
        "sgdb_service": sgdb_service,
        "metadata_service": metadata_service,
        "achievements_service": achievements_service,
        "migration_service": migration_service,
    }
