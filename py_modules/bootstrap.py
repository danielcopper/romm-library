"""Composition root — wires adapters for the plugin.

Called from ``Plugin._main()`` to create adapter instances with
the correct Decky paths and logger.  Returns a dict so that
``_main()`` can assign them to the plugin's lazy-property backing
attributes (bypassing auto-creation from ``self.settings``).
"""

import logging

from adapters.persistence import PersistenceAdapter
from adapters.romm.client import RommHttpClient


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
    dict with keys ``persistence`` and ``http_client``.
    """
    persistence = PersistenceAdapter(settings_dir, runtime_dir, logger)
    http_client = RommHttpClient(settings, plugin_dir, logger)
    return {
        "persistence": persistence,
        "http_client": http_client,
    }
