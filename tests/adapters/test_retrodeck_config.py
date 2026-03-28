"""Tests for adapters.retrodeck_config.RetroDeckConfigAdapter."""

from __future__ import annotations

import json
import logging
import os
import time

from adapters.retrodeck_config import RetroDeckConfigAdapter


def _make_adapter(tmp_path, config: dict | None = None) -> RetroDeckConfigAdapter:
    """Create adapter with optional retrodeck.json config."""
    user_home = str(tmp_path)
    if config is not None:
        config_dir = tmp_path / ".var" / "app" / "net.retrodeck.retrodeck" / "config" / "retrodeck"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "retrodeck.json").write_text(json.dumps(config))
    return RetroDeckConfigAdapter(user_home=user_home, logger=logging.getLogger("test"))


class TestPathResolution:
    def test_bios_path_from_config(self, tmp_path):
        adapter = _make_adapter(tmp_path, {"paths": {"bios_path": "/custom/bios"}})
        assert adapter.get_bios_path() == "/custom/bios"

    def test_bios_path_fallback(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        assert adapter.get_bios_path() == os.path.join(str(tmp_path), "retrodeck", "bios")

    def test_roms_path_from_config(self, tmp_path):
        adapter = _make_adapter(tmp_path, {"paths": {"roms_path": "/custom/roms"}})
        assert adapter.get_roms_path() == "/custom/roms"

    def test_roms_path_fallback(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        assert adapter.get_roms_path() == os.path.join(str(tmp_path), "retrodeck", "roms")

    def test_saves_path_from_config(self, tmp_path):
        adapter = _make_adapter(tmp_path, {"paths": {"saves_path": "/custom/saves"}})
        assert adapter.get_saves_path() == "/custom/saves"

    def test_retrodeck_home_from_config(self, tmp_path):
        adapter = _make_adapter(tmp_path, {"paths": {"rd_home_path": "/custom/home"}})
        assert adapter.get_retrodeck_home() == "/custom/home"

    def test_retrodeck_home_fallback(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        assert adapter.get_retrodeck_home() == os.path.join(str(tmp_path), "retrodeck", "")

    def test_empty_path_uses_fallback(self, tmp_path):
        adapter = _make_adapter(tmp_path, {"paths": {"roms_path": ""}})
        assert adapter.get_roms_path() == os.path.join(str(tmp_path), "retrodeck", "roms")

    def test_missing_paths_key_uses_fallback(self, tmp_path):
        adapter = _make_adapter(tmp_path, {"other": "data"})
        assert adapter.get_roms_path() == os.path.join(str(tmp_path), "retrodeck", "roms")

    def test_malformed_json_uses_fallback(self, tmp_path):
        config_dir = tmp_path / ".var" / "app" / "net.retrodeck.retrodeck" / "config" / "retrodeck"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "retrodeck.json").write_text("not valid json")
        adapter = RetroDeckConfigAdapter(user_home=str(tmp_path), logger=logging.getLogger("test"))
        assert adapter.get_bios_path() == os.path.join(str(tmp_path), "retrodeck", "bios")


class TestTTLCache:
    def test_cache_returns_same_value(self, tmp_path):
        adapter = _make_adapter(tmp_path, {"paths": {"bios_path": "/first"}})
        assert adapter.get_bios_path() == "/first"
        # Overwrite config — should still return cached value
        config_dir = tmp_path / ".var" / "app" / "net.retrodeck.retrodeck" / "config" / "retrodeck"
        (config_dir / "retrodeck.json").write_text(json.dumps({"paths": {"bios_path": "/second"}}))
        assert adapter.get_bios_path() == "/first"

    def test_cache_expires_after_ttl(self, tmp_path):
        adapter = _make_adapter(tmp_path, {"paths": {"bios_path": "/first"}})
        assert adapter.get_bios_path() == "/first"
        # Force cache expiry
        adapter._cache_time = time.monotonic() - 31
        config_dir = tmp_path / ".var" / "app" / "net.retrodeck.retrodeck" / "config" / "retrodeck"
        (config_dir / "retrodeck.json").write_text(json.dumps({"paths": {"bios_path": "/second"}}))
        assert adapter.get_bios_path() == "/second"


class TestRetroArchSaveSorting:
    def test_defaults_when_no_cfg(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        sort_by_content, sort_by_core = adapter.get_retroarch_save_sorting()
        assert sort_by_content is True
        assert sort_by_core is False

    def test_reads_sort_by_content_false(self, tmp_path):
        cfg_dir = tmp_path / ".var" / "app" / "net.retrodeck.retrodeck" / "config" / "retroarch"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "retroarch.cfg").write_text(
            'sort_savefiles_by_content_enable = "false"\nsort_savefiles_enable = "false"\n'
        )
        adapter = _make_adapter(tmp_path)
        sort_by_content, sort_by_core = adapter.get_retroarch_save_sorting()
        assert sort_by_content is False
        assert sort_by_core is False

    def test_reads_sort_by_core_true(self, tmp_path):
        cfg_dir = tmp_path / ".var" / "app" / "net.retrodeck.retrodeck" / "config" / "retroarch"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "retroarch.cfg").write_text(
            'sort_savefiles_by_content_enable = "true"\nsort_savefiles_enable = "true"\n'
        )
        adapter = _make_adapter(tmp_path)
        sort_by_content, sort_by_core = adapter.get_retroarch_save_sorting()
        assert sort_by_content is True
        assert sort_by_core is True
