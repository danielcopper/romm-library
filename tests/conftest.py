import sys
import os
import logging
import tempfile
from unittest.mock import MagicMock, AsyncMock

# Mirror Decky's sys.path setup: add py_modules/ so `from lib.xxx import` works
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_project_root, "py_modules"))

# Create mock decky module before any imports of main
mock_decky = MagicMock()
mock_decky.DECKY_PLUGIN_DIR = _project_root
mock_decky.DECKY_PLUGIN_SETTINGS_DIR = tempfile.mkdtemp()
mock_decky.DECKY_PLUGIN_RUNTIME_DIR = tempfile.mkdtemp()
mock_decky.DECKY_PLUGIN_LOG_DIR = tempfile.mkdtemp()
mock_decky.DECKY_USER_HOME = os.path.expanduser("~")
mock_decky.logger = logging.getLogger("test_romm")
mock_decky.emit = AsyncMock()

sys.modules["decky"] = mock_decky
