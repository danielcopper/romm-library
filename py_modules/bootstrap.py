"""Composition root — wires adapters and services for the plugin.

Called from ``Plugin._main()`` to create adapter instances with
the correct Decky paths and logger.  Returns a dict so that
``_main()`` can assign them to the plugin's lazy-property backing
attributes (bypassing auto-creation from ``self.settings``).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from adapters.persistence import PersistenceAdapter
from adapters.romm.client import RommHttpClient
from adapters.romm.save_api.v46 import SaveApiV46
from services.playtime import PlaytimeService
from services.save_sync import SaveSyncService


def bootstrap(
    *,
    settings_dir: str,
    runtime_dir: str,
    plugin_dir: str,
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
        The live settings dict (passed by reference to ``RommHttpClient``).

    Returns
    -------
    dict with keys ``persistence``, ``http_client``, and ``wire_services``
    (a factory callable for deferred service creation).
    """
    persistence = PersistenceAdapter(settings_dir, runtime_dir, logger)
    http_client = RommHttpClient(settings, plugin_dir, logger)
    save_api = SaveApiV46(http_client)

    return {
        "persistence": persistence,
        "http_client": http_client,
        "save_api": save_api,
    }


def wire_services(
    *,
    save_api: Any,
    http_client: RommHttpClient,
    state: dict,
    save_sync_state: dict,
    loop: asyncio.AbstractEventLoop,
    logger: logging.Logger,
    runtime_dir: str,
    get_saves_path: Any,
    save_state_fn: Any,
) -> dict:
    """Create service instances after plugin state is initialised.

    Called from ``Plugin._main()`` after ``_init_save_sync_state`` /
    ``_load_save_sync_state`` so that services receive live references
    to the fully-populated state dicts.

    Returns
    -------
    dict with keys ``save_sync_service`` and ``playtime_service``.
    """
    save_sync_service = SaveSyncService(
        save_api=save_api,
        with_retry=http_client.with_retry,
        is_retryable=http_client.is_retryable,
        state=state,
        save_sync_state=save_sync_state,
        loop=loop,
        logger=logger,
        runtime_dir=runtime_dir,
        get_saves_path=get_saves_path,
    )

    playtime_service = PlaytimeService(
        save_api=save_api,
        with_retry=http_client.with_retry,
        is_retryable=http_client.is_retryable,
        save_sync_state=save_sync_state,
        loop=loop,
        logger=logger,
        save_state=save_state_fn,
    )

    return {
        "save_sync_service": save_sync_service,
        "playtime_service": playtime_service,
    }
