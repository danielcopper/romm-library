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
from typing import Any

from adapters.persistence import PersistenceAdapter
from adapters.romm.http import RommHttpAdapter
from adapters.romm.version_router import VersionRouter
from adapters.steam_config import SteamConfigAdapter
from services.achievements import AchievementsService
from services.artwork import ArtworkService
from services.downloads import DownloadService
from services.firmware import FirmwareService
from services.library import LibraryService
from services.metadata import MetadataService
from services.migration import MigrationService
from services.playtime import PlaytimeService
from services.protocols import HttpAdapter
from services.protocols import SteamConfigAdapter as SteamConfigProtocol
from services.saves import SaveService


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
    steam_config = SteamConfigAdapter(user_home=user_home, logger=logger)

    return {
        "persistence": persistence,
        "http_adapter": http_adapter,
        "save_api": version_router,
        "version_router": version_router,
        "steam_config": steam_config,
    }


def wire_services(
    *,
    save_api: Any,
    http_adapter: HttpAdapter,
    steam_config: SteamConfigProtocol,
    state: dict,
    settings: dict,
    metadata_cache: dict,
    save_sync_state: dict,
    loop: asyncio.AbstractEventLoop,
    logger: logging.Logger,
    plugin_dir: str,
    runtime_dir: str,
    emit: Any,
    get_saves_path: Any,
    save_state: Callable,
    save_settings_to_disk: Callable,
    save_metadata_cache: Callable,
    log_debug: Callable,
) -> dict:
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
        save_api=save_api,
        with_retry=http_adapter.with_retry,
        is_retryable=http_adapter.is_retryable,
        state=state,
        save_sync_state=save_sync_state,
        loop=loop,
        logger=logger,
        runtime_dir=runtime_dir,
        get_saves_path=get_saves_path,
    )

    playtime_service = PlaytimeService(
        save_api=save_api,
        with_retry=http_adapter.with_retry,
        is_retryable=http_adapter.is_retryable,
        save_sync_state=save_sync_state,
        loop=loop,
        logger=logger,
        save_state=save_sync_service.save_state,
    )

    metadata_service = MetadataService(
        http_adapter=http_adapter,
        state=state,
        metadata_cache=metadata_cache,
        loop=loop,
        logger=logger,
        save_metadata_cache=save_metadata_cache,
        log_debug=log_debug,
    )

    sync_service = LibraryService(
        http_adapter=http_adapter,
        steam_config=steam_config,
        state=state,
        settings=settings,
        metadata_cache=metadata_cache,
        loop=loop,
        logger=logger,
        plugin_dir=plugin_dir,
        emit=emit,
        save_state=save_state,
        save_settings_to_disk=save_settings_to_disk,
        log_debug=log_debug,
        metadata_service=metadata_service,
    )

    download_service = DownloadService(
        http_adapter=http_adapter,
        state=state,
        save_sync_state=save_sync_state,
        loop=loop,
        logger=logger,
        runtime_dir=runtime_dir,
        emit=emit,
        save_state=save_state,
        save_save_sync_state=save_sync_service.save_state,
    )

    firmware_service = FirmwareService(
        http_adapter=http_adapter,
        state=state,
        loop=loop,
        logger=logger,
        plugin_dir=plugin_dir,
        save_state=save_state,
    )

    sgdb_service = ArtworkService(
        http_adapter=http_adapter,
        steam_config=steam_config,
        state=state,
        settings=settings,
        loop=loop,
        logger=logger,
        runtime_dir=runtime_dir,
        save_state=save_state,
        save_settings_to_disk=save_settings_to_disk,
        pending_sync=sync_service.pending_sync,
    )

    achievements_service = AchievementsService(
        http_adapter=http_adapter,
        state=state,
        loop=loop,
        logger=logger,
        log_debug=log_debug,
    )

    migration_service = MigrationService(
        state=state,
        loop=loop,
        logger=logger,
        save_state=save_state,
        emit=emit,
        firmware_service_bios_files_index=firmware_service._bios_files_index,
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
