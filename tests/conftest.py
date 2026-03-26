import logging
import os
import sys
import tempfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Mirror Decky's sys.path setup: add py_modules/ so `from lib.xxx import` works
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_tests_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_project_root, "py_modules"))
# Add tests/ root so subdirectory tests can still import from fakes/ and conftest
sys.path.insert(0, _tests_root)


class _DeckyMock(MagicMock):
    """MagicMock that keeps retrodeck_config and es_de_config in sync when
    DECKY_USER_HOME or DECKY_PLUGIN_DIR are reassigned in tests.

    Without this, tests that do ``decky.DECKY_USER_HOME = str(tmp_path)``
    would update the mock attribute but not the domain module's cached value,
    which is now stored via configure() rather than read lazily.
    """

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name == "DECKY_USER_HOME":
            try:
                from domain import retrodeck_config

                retrodeck_config.configure(user_home=value)
                retrodeck_config._cached_config = None
                retrodeck_config._cache_time = 0.0
                retrodeck_config._cache_config_path = None
            except Exception:
                pass
        elif name == "DECKY_PLUGIN_DIR":
            try:
                from domain import es_de_config

                logger = super().__getattribute__("logger")
                es_de_config.configure(plugin_dir=value, logger=logger)
            except Exception:
                pass


# Create mock decky module before any imports of main
mock_decky = _DeckyMock()
mock_decky.DECKY_PLUGIN_DIR = _project_root
mock_decky.DECKY_PLUGIN_SETTINGS_DIR = tempfile.mkdtemp()
mock_decky.DECKY_PLUGIN_RUNTIME_DIR = tempfile.mkdtemp()
mock_decky.DECKY_PLUGIN_LOG_DIR = tempfile.mkdtemp()
mock_decky.DECKY_USER_HOME = os.path.expanduser("~")
mock_decky.logger = logging.getLogger("test_romm")
mock_decky.emit = AsyncMock()

sys.modules["decky"] = mock_decky


def _make_testable_plugin():
    """Return a TestablePlugin instance with test-only attributes declared."""
    # Import here to ensure decky mock is already installed
    from main import Plugin

    class TestablePlugin(Plugin):
        """Plugin subclass that declares test-only attributes for type safety."""

        _fake_api: Any
        _resolve_system: Any

    return TestablePlugin()


@pytest.fixture(autouse=True)
def _reset_retrodeck_config_user_home():
    """Reset retrodeck_config and es_de_config module-level state between every test.

    Calls configure() with the mock decky values so that services using these
    modules work without explicit configure() calls in test bodies.
    Tests that need a specific user_home can set decky.DECKY_USER_HOME = str(tmp_path),
    which will automatically call retrodeck_config.configure() via _DeckyMock.
    """
    from domain import es_de_config, retrodeck_config

    # Fresh temp dirs per test — ensures no cross-test pollution
    mock_decky.DECKY_USER_HOME = os.path.expanduser("~")
    mock_decky.DECKY_PLUGIN_DIR = _project_root
    _fresh_settings = tempfile.mkdtemp()
    _fresh_runtime = tempfile.mkdtemp()
    mock_decky.DECKY_PLUGIN_SETTINGS_DIR = _fresh_settings
    mock_decky.DECKY_PLUGIN_RUNTIME_DIR = _fresh_runtime
    retrodeck_config._cached_config = None
    retrodeck_config._cache_time = 0.0
    retrodeck_config._cache_config_path = None
    es_de_config.configure(plugin_dir=_project_root, logger=logging.getLogger("test_romm"))
    yield
    retrodeck_config._user_home = None
    retrodeck_config._cached_config = None
    retrodeck_config._cache_time = 0.0
    retrodeck_config._cache_config_path = None
