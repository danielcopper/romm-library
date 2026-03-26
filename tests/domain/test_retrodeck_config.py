import json
import os

import pytest

# conftest.py patches decky before this import
from domain import retrodeck_config


@pytest.fixture(autouse=True)
def _reset_retrodeck_cache():
    """Reset retrodeck_config module-level cache and configured user home between tests."""
    retrodeck_config._cached_config = None
    retrodeck_config._cache_time = 0.0
    retrodeck_config._cache_config_path = None
    retrodeck_config._user_home = None


class TestGetBiosPath:
    def test_from_config(self, tmp_path):
        retrodeck_config.configure(user_home=str(tmp_path))

        config_dir = tmp_path / ".var" / "app" / "net.retrodeck.retrodeck" / "config" / "retrodeck"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "retrodeck.json"
        config_file.write_text(json.dumps({"paths": {"bios_path": "/run/media/deck/SD/retrodeck/bios"}}))

        result = retrodeck_config.get_bios_path()
        assert result == "/run/media/deck/SD/retrodeck/bios"

    def test_fallback_when_config_missing(self, tmp_path):
        retrodeck_config.configure(user_home=str(tmp_path))

        result = retrodeck_config.get_bios_path()
        assert result == os.path.join(str(tmp_path), "retrodeck", "bios")


class TestGetRomsPath:
    def test_from_config(self, tmp_path):
        retrodeck_config.configure(user_home=str(tmp_path))

        config_dir = tmp_path / ".var" / "app" / "net.retrodeck.retrodeck" / "config" / "retrodeck"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "retrodeck.json"
        config_file.write_text(json.dumps({"paths": {"roms_path": "/run/media/deck/SD/retrodeck/roms"}}))

        result = retrodeck_config.get_roms_path()
        assert result == "/run/media/deck/SD/retrodeck/roms"

    def test_fallback_when_config_missing(self, tmp_path):
        retrodeck_config.configure(user_home=str(tmp_path))

        result = retrodeck_config.get_roms_path()
        assert result == os.path.join(str(tmp_path), "retrodeck", "roms")


class TestGetSavesPath:
    def test_from_config(self, tmp_path):
        retrodeck_config.configure(user_home=str(tmp_path))

        config_dir = tmp_path / ".var" / "app" / "net.retrodeck.retrodeck" / "config" / "retrodeck"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "retrodeck.json"
        config_file.write_text(json.dumps({"paths": {"saves_path": "/run/media/deck/SD/retrodeck/saves"}}))

        result = retrodeck_config.get_saves_path()
        assert result == "/run/media/deck/SD/retrodeck/saves"


class TestGetRetroDeckHome:
    def test_from_config(self, tmp_path):
        retrodeck_config.configure(user_home=str(tmp_path))

        config_dir = tmp_path / ".var" / "app" / "net.retrodeck.retrodeck" / "config" / "retrodeck"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "retrodeck.json"
        config_file.write_text(json.dumps({"paths": {"rd_home_path": "/run/media/deck/SD/retrodeck"}}))

        result = retrodeck_config.get_retrodeck_home()
        assert result == "/run/media/deck/SD/retrodeck"

    def test_fallback_when_config_missing(self, tmp_path):
        retrodeck_config.configure(user_home=str(tmp_path))

        result = retrodeck_config.get_retrodeck_home()
        # fallback_subdir is "" for home, so returns ~/retrodeck/
        assert result == os.path.join(str(tmp_path), "retrodeck", "")


class TestTTLCache:
    def test_cache_returns_same_result_without_rereading(self, tmp_path):
        """Second call within TTL should return cached result."""
        retrodeck_config.configure(user_home=str(tmp_path))

        config_dir = tmp_path / ".var" / "app" / "net.retrodeck.retrodeck" / "config" / "retrodeck"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "retrodeck.json"
        config_file.write_text(json.dumps({"paths": {"bios_path": "/original/bios"}}))

        result1 = retrodeck_config.get_bios_path()
        assert result1 == "/original/bios"

        # Change file — should still return cached value within TTL
        config_file.write_text(json.dumps({"paths": {"bios_path": "/changed/bios"}}))
        result2 = retrodeck_config.get_bios_path()
        assert result2 == "/original/bios"

    def test_cache_expires_after_ttl(self, tmp_path, monkeypatch):
        """After TTL expires, cache should re-read from disk."""
        retrodeck_config.configure(user_home=str(tmp_path))

        config_dir = tmp_path / ".var" / "app" / "net.retrodeck.retrodeck" / "config" / "retrodeck"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "retrodeck.json"
        config_file.write_text(json.dumps({"paths": {"bios_path": "/original/bios"}}))

        result1 = retrodeck_config.get_bios_path()
        assert result1 == "/original/bios"

        # Change file and expire cache by advancing monotonic time
        config_file.write_text(json.dumps({"paths": {"bios_path": "/changed/bios"}}))
        import time

        original_monotonic = time.monotonic
        monkeypatch.setattr(time, "monotonic", lambda: original_monotonic() + 31)
        retrodeck_config._cache_time = 0  # force expiry

        result2 = retrodeck_config.get_bios_path()
        assert result2 == "/changed/bios"

    def test_cache_reset_allows_new_values(self, tmp_path):
        """After cache reset (via fixture), new config values are picked up."""
        retrodeck_config.configure(user_home=str(tmp_path))

        config_dir = tmp_path / ".var" / "app" / "net.retrodeck.retrodeck" / "config" / "retrodeck"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "retrodeck.json"
        config_file.write_text(json.dumps({"paths": {"bios_path": "/original/bios"}}))

        result1 = retrodeck_config.get_bios_path()
        assert result1 == "/original/bios"

        # Fixture resets cache between tests, so writing new config
        # and clearing cache manually simulates that
        retrodeck_config._cached_config = None
        retrodeck_config._cache_time = 0.0
        config_file.write_text(json.dumps({"paths": {"bios_path": "/new/bios"}}))
        result2 = retrodeck_config.get_bios_path()
        assert result2 == "/new/bios"


class TestEdgeCases:
    def test_fallback_when_key_missing(self, tmp_path):
        """Config exists but missing the requested path key."""
        retrodeck_config.configure(user_home=str(tmp_path))

        config_dir = tmp_path / ".var" / "app" / "net.retrodeck.retrodeck" / "config" / "retrodeck"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "retrodeck.json"
        config_file.write_text(json.dumps({"paths": {"other_key": "/some/path"}}))

        result = retrodeck_config.get_bios_path()
        assert result == os.path.join(str(tmp_path), "retrodeck", "bios")

    def test_fallback_when_json_malformed(self, tmp_path):
        """Corrupt JSON falls back gracefully."""
        retrodeck_config.configure(user_home=str(tmp_path))

        config_dir = tmp_path / ".var" / "app" / "net.retrodeck.retrodeck" / "config" / "retrodeck"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "retrodeck.json"
        config_file.write_text("{corrupt json!!!")

        result = retrodeck_config.get_bios_path()
        assert result == os.path.join(str(tmp_path), "retrodeck", "bios")

    def test_fallback_when_path_empty_string(self, tmp_path):
        """Key exists but value is empty string — should fallback."""
        retrodeck_config.configure(user_home=str(tmp_path))

        config_dir = tmp_path / ".var" / "app" / "net.retrodeck.retrodeck" / "config" / "retrodeck"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "retrodeck.json"
        config_file.write_text(json.dumps({"paths": {"bios_path": ""}}))

        result = retrodeck_config.get_bios_path()
        assert result == os.path.join(str(tmp_path), "retrodeck", "bios")

    def test_no_paths_key_in_config(self, tmp_path):
        """Config exists but has no 'paths' key at all."""
        retrodeck_config.configure(user_home=str(tmp_path))

        config_dir = tmp_path / ".var" / "app" / "net.retrodeck.retrodeck" / "config" / "retrodeck"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "retrodeck.json"
        config_file.write_text(json.dumps({"version": "1.0"}))

        result = retrodeck_config.get_roms_path()
        assert result == os.path.join(str(tmp_path), "retrodeck", "roms")
