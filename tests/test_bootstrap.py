"""Tests for the bootstrap composition root."""

import logging

from adapters.persistence import PersistenceAdapter
from adapters.romm.client import RommHttpClient
from bootstrap import bootstrap


class TestBootstrap:
    def test_returns_persistence_adapter(self, tmp_path):
        result = bootstrap(
            settings_dir=str(tmp_path / "settings"),
            runtime_dir=str(tmp_path / "runtime"),
            plugin_dir=str(tmp_path / "plugin"),
            logger=logging.getLogger("test"),
            settings={},
        )
        assert "persistence" in result
        assert isinstance(result["persistence"], PersistenceAdapter)

    def test_returns_http_client(self, tmp_path):
        result = bootstrap(
            settings_dir=str(tmp_path / "settings"),
            runtime_dir=str(tmp_path / "runtime"),
            plugin_dir=str(tmp_path / "plugin"),
            logger=logging.getLogger("test"),
            settings={},
        )
        assert "http_client" in result
        assert isinstance(result["http_client"], RommHttpClient)

    def test_http_client_shares_settings_reference(self, tmp_path):
        settings = {"romm_url": "http://example.com"}
        result = bootstrap(
            settings_dir=str(tmp_path / "settings"),
            runtime_dir=str(tmp_path / "runtime"),
            plugin_dir=str(tmp_path / "plugin"),
            logger=logging.getLogger("test"),
            settings=settings,
        )
        # Mutate original — client should see the change
        settings["romm_url"] = "http://changed.com"
        assert result["http_client"]._settings["romm_url"] == "http://changed.com"

    def test_persistence_has_correct_paths(self, tmp_path):
        settings_dir = str(tmp_path / "s")
        runtime_dir = str(tmp_path / "r")
        result = bootstrap(
            settings_dir=settings_dir,
            runtime_dir=runtime_dir,
            plugin_dir=str(tmp_path / "p"),
            logger=logging.getLogger("test"),
            settings={},
        )
        assert result["persistence"]._settings_dir == settings_dir
        assert result["persistence"]._runtime_dir == runtime_dir
