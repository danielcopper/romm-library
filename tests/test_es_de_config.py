"""Tests for lib/es_de_config module."""

import json
import os
import tempfile
from unittest import mock

import pytest

# conftest.py patches decky before this import
# main.py adds py_modules to sys.path (provides vdf, etc.)
from main import Plugin  # noqa: F401

from lib import es_de_config


# --- Helpers ---

SAMPLE_ES_SYSTEMS_XML = """\
<?xml version="1.0"?>
<systemList>
  <system>
    <name>gba</name>
    <command label="mGBA">%EMULATOR_RETROARCH% -L %CORE_RETROARCH%/mgba_libretro.so %ROM%</command>
    <command label="gpSP">%EMULATOR_RETROARCH% -L %CORE_RETROARCH%/gpsp_libretro.so %ROM%</command>
    <command label="VBA-M">%EMULATOR_RETROARCH% -L %CORE_RETROARCH%/vbam_libretro.so %ROM%</command>
    <command label="mGBA Standalone">%EMULATOR_MGBA% %ROM%</command>
  </system>
  <system>
    <name>snes</name>
    <command label="Snes9x">%EMULATOR_RETROARCH% -L %CORE_RETROARCH%/snes9x_libretro.so %ROM%</command>
    <command label="bsnes">%EMULATOR_RETROARCH% -L %CORE_RETROARCH%/bsnes_libretro.so %ROM%</command>
  </system>
</systemList>
"""

SAMPLE_GAMELIST_WITH_OVERRIDE = """\
<?xml version="1.0"?>
<gameList>
  <alternativeEmulator>
    <label>gpSP</label>
  </alternativeEmulator>
</gameList>
"""

SAMPLE_GAMELIST_NO_OVERRIDE = """\
<?xml version="1.0"?>
<gameList>
  <game>
    <path>./some_game.gba</path>
    <name>Some Game</name>
  </game>
</gameList>
"""


def _write_temp_xml(content):
    """Write content to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".xml")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


class TestFindEsSystemsXml:
    def setup_method(self):
        es_de_config._reset_cache()

    @mock.patch("lib.es_de_config.os.path.exists")
    def test_finds_xml_in_linux_path(self, mock_exists):
        mock_exists.return_value = True
        result = es_de_config.find_es_systems_xml()
        assert result == es_de_config._ES_SYSTEMS_CANDIDATES[0]
        assert "linux" in result

    @mock.patch("lib.es_de_config.os.path.exists")
    def test_falls_back_to_unix_path(self, mock_exists):
        # linux/ doesn't exist, unix/ does
        mock_exists.side_effect = [False, True]
        result = es_de_config.find_es_systems_xml()
        assert result == es_de_config._ES_SYSTEMS_CANDIDATES[1]
        assert "unix" in result

    @mock.patch("lib.es_de_config.os.path.exists")
    def test_returns_none_when_not_found(self, mock_exists):
        mock_exists.return_value = False
        result = es_de_config.find_es_systems_xml()
        assert result is None


class TestParseEsSystems:
    def setup_method(self):
        es_de_config._reset_cache()

    def test_parses_system_with_retroarch_cores(self):
        path = _write_temp_xml(SAMPLE_ES_SYSTEMS_XML)
        try:
            result = es_de_config.parse_es_systems(path)
            assert "gba" in result
            gba = result["gba"]
            assert gba["default_core"] == "mgba_libretro"
            assert gba["default_label"] == "mGBA"
            assert gba["cores"] == {
                "mgba_libretro": "mGBA",
                "gpsp_libretro": "gpSP",
                "vbam_libretro": "VBA-M",
            }
            assert gba["label_to_core"] == {
                "mGBA": "mgba_libretro",
                "gpSP": "gpsp_libretro",
                "VBA-M": "vbam_libretro",
            }
        finally:
            os.unlink(path)

    def test_first_retroarch_command_is_default(self):
        path = _write_temp_xml(SAMPLE_ES_SYSTEMS_XML)
        try:
            result = es_de_config.parse_es_systems(path)
            snes = result["snes"]
            assert snes["default_core"] == "snes9x_libretro"
            assert snes["default_label"] == "Snes9x"
        finally:
            os.unlink(path)

    def test_standalone_emulators_excluded(self):
        path = _write_temp_xml(SAMPLE_ES_SYSTEMS_XML)
        try:
            result = es_de_config.parse_es_systems(path)
            gba = result["gba"]
            # "mGBA Standalone" should NOT be in cores (no %CORE_RETROARCH%)
            assert "mGBA Standalone" not in gba["label_to_core"]
            assert len(gba["cores"]) == 3  # only the 3 RetroArch cores
        finally:
            os.unlink(path)

    def test_invalid_xml_returns_empty(self):
        path = _write_temp_xml("this is not xml at all {{{")
        try:
            result = es_de_config.parse_es_systems(path)
            assert result == {}
        finally:
            os.unlink(path)

    def test_wrong_root_tag_returns_empty(self):
        path = _write_temp_xml('<?xml version="1.0"?><wrongTag><system><name>gba</name></system></wrongTag>')
        try:
            result = es_de_config.parse_es_systems(path)
            assert result == {}
        finally:
            os.unlink(path)

    def test_system_with_only_standalone_cores(self):
        xml = """\
<?xml version="1.0"?>
<systemList>
  <system>
    <name>switch</name>
    <command label="Yuzu">%EMULATOR_YUZU% %ROM%</command>
    <command label="Ryujinx">%EMULATOR_RYUJINX% %ROM%</command>
  </system>
</systemList>
"""
        path = _write_temp_xml(xml)
        try:
            result = es_de_config.parse_es_systems(path)
            assert "switch" in result
            assert result["switch"]["default_core"] is None
            assert result["switch"]["default_label"] is None
            assert result["switch"]["cores"] == {}
        finally:
            os.unlink(path)

    def test_label_to_core_mapping(self):
        path = _write_temp_xml(SAMPLE_ES_SYSTEMS_XML)
        try:
            result = es_de_config.parse_es_systems(path)
            gba = result["gba"]
            # Verify label -> core_so reverse mapping
            assert gba["label_to_core"]["mGBA"] == "mgba_libretro"
            assert gba["label_to_core"]["gpSP"] == "gpsp_libretro"
            assert gba["label_to_core"]["VBA-M"] == "vbam_libretro"
        finally:
            os.unlink(path)


class TestGetSystemOverride:
    def setup_method(self):
        es_de_config._reset_cache()

    def test_no_gamelist_returns_none(self):
        result = es_de_config.get_system_override("/nonexistent/path", "gba")
        assert result is None

    def test_gamelist_with_alternative_emulator(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gamelist_dir = os.path.join(tmpdir, "ES-DE", "gamelists", "gba")
            os.makedirs(gamelist_dir)
            gamelist_path = os.path.join(gamelist_dir, "gamelist.xml")
            with open(gamelist_path, "w") as f:
                f.write(SAMPLE_GAMELIST_WITH_OVERRIDE)

            result = es_de_config.get_system_override(tmpdir, "gba")
            assert result == "gpSP"

    def test_gamelist_without_override_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gamelist_dir = os.path.join(tmpdir, "ES-DE", "gamelists", "gba")
            os.makedirs(gamelist_dir)
            gamelist_path = os.path.join(gamelist_dir, "gamelist.xml")
            with open(gamelist_path, "w") as f:
                f.write(SAMPLE_GAMELIST_NO_OVERRIDE)

            result = es_de_config.get_system_override(tmpdir, "gba")
            assert result is None

    def test_malformed_gamelist_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gamelist_dir = os.path.join(tmpdir, "ES-DE", "gamelists", "gba")
            os.makedirs(gamelist_dir)
            gamelist_path = os.path.join(gamelist_dir, "gamelist.xml")
            with open(gamelist_path, "w") as f:
                f.write("this is garbage not xml {{{")

            result = es_de_config.get_system_override(tmpdir, "gba")
            assert result is None


class TestGetActiveCore:
    def setup_method(self):
        es_de_config._reset_cache()

    GBA_SYSTEM_INFO = {
        "gba": {
            "default_core": "mgba_libretro",
            "default_label": "mGBA",
            "cores": {
                "mgba_libretro": "mGBA",
                "gpsp_libretro": "gpSP",
                "vbam_libretro": "VBA-M",
            },
            "label_to_core": {
                "mGBA": "mgba_libretro",
                "gpSP": "gpsp_libretro",
                "VBA-M": "vbam_libretro",
            },
        }
    }

    @mock.patch("lib.es_de_config._load_es_systems")
    @mock.patch("lib.es_de_config.get_system_override", return_value=None)
    @mock.patch("lib.retrodeck_config.get_retrodeck_home", return_value="/fake/retrodeck")
    def test_default_core_from_live_xml(self, mock_home, mock_override, mock_load):
        mock_load.return_value = self.GBA_SYSTEM_INFO
        result = es_de_config.get_active_core("gba")
        assert result == ("mgba_libretro", "mGBA")

    @mock.patch("lib.es_de_config._load_es_systems")
    @mock.patch("lib.es_de_config.get_system_override", return_value="gpSP")
    @mock.patch("lib.retrodeck_config.get_retrodeck_home", return_value="/fake/retrodeck")
    def test_system_override_takes_precedence(self, mock_home, mock_override, mock_load):
        mock_load.return_value = self.GBA_SYSTEM_INFO
        result = es_de_config.get_active_core("gba")
        assert result == ("gpsp_libretro", "gpSP")

    @mock.patch("lib.es_de_config._load_es_systems")
    @mock.patch("lib.es_de_config._load_core_defaults")
    @mock.patch("lib.retrodeck_config.get_retrodeck_home", return_value=None)
    def test_fallback_to_core_defaults(self, mock_home, mock_defaults, mock_load):
        mock_load.return_value = {}
        mock_defaults.return_value = {
            "gba": {
                "default_core": "mgba_libretro",
                "default_label": "mGBA",
                "cores": {"mgba_libretro": "mGBA"},
            }
        }
        result = es_de_config.get_active_core("gba")
        assert result == ("mgba_libretro", "mGBA")

    @mock.patch("lib.es_de_config._load_es_systems")
    @mock.patch("lib.es_de_config._load_core_defaults")
    @mock.patch("lib.retrodeck_config.get_retrodeck_home", return_value=None)
    def test_returns_none_when_all_fail(self, mock_home, mock_defaults, mock_load):
        mock_load.return_value = {}
        mock_defaults.return_value = {}
        result = es_de_config.get_active_core("gba")
        assert result == (None, None)

    @mock.patch("lib.es_de_config._load_es_systems")
    @mock.patch("lib.es_de_config._load_core_defaults")
    @mock.patch("lib.retrodeck_config.get_retrodeck_home", return_value=None)
    def test_unknown_system_returns_none(self, mock_home, mock_defaults, mock_load):
        mock_load.return_value = self.GBA_SYSTEM_INFO
        mock_defaults.return_value = {}
        result = es_de_config.get_active_core("totally_unknown_system")
        assert result == (None, None)


class TestGetAvailableCores:
    def setup_method(self):
        es_de_config._reset_cache()

    GBA_SYSTEM_INFO = {
        "gba": {
            "default_core": "mgba_libretro",
            "default_label": "mGBA",
            "cores": {
                "mgba_libretro": "mGBA",
                "gpsp_libretro": "gpSP",
                "vbam_libretro": "VBA-M",
            },
            "label_to_core": {
                "mGBA": "mgba_libretro",
                "gpSP": "gpsp_libretro",
                "VBA-M": "vbam_libretro",
            },
        }
    }

    @mock.patch("lib.es_de_config._load_es_systems")
    def test_returns_cores_from_live_xml(self, mock_load):
        mock_load.return_value = self.GBA_SYSTEM_INFO
        result = es_de_config.get_available_cores("gba")
        assert len(result) == 3
        labels = [c["label"] for c in result]
        assert "mGBA" in labels
        assert "gpSP" in labels
        assert "VBA-M" in labels
        # Check is_default
        default = [c for c in result if c["is_default"]]
        assert len(default) == 1
        assert default[0]["core_so"] == "mgba_libretro"

    @mock.patch("lib.es_de_config._load_es_systems")
    @mock.patch("lib.es_de_config._load_core_defaults")
    def test_falls_back_to_core_defaults(self, mock_defaults, mock_load):
        mock_load.return_value = {}
        mock_defaults.return_value = {
            "gba": {
                "default_core": "mgba_libretro",
                "default_label": "mGBA",
                "cores": {"mgba_libretro": "mGBA", "gpsp_libretro": "gpSP"},
            }
        }
        result = es_de_config.get_available_cores("gba")
        assert len(result) == 2

    @mock.patch("lib.es_de_config._load_es_systems")
    @mock.patch("lib.es_de_config._load_core_defaults")
    def test_unknown_system_returns_empty(self, mock_defaults, mock_load):
        mock_load.return_value = {}
        mock_defaults.return_value = {}
        result = es_de_config.get_available_cores("unknown_system")
        assert result == []


class TestSetSystemOverride:
    def setup_method(self):
        es_de_config._reset_cache()

    def test_creates_new_gamelist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            es_de_config.set_system_override(tmpdir, "gba", "gpSP")
            result = es_de_config.get_system_override(tmpdir, "gba")
            assert result == "gpSP"

    def test_updates_existing_gamelist_preserves_games(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gamelist_dir = os.path.join(tmpdir, "ES-DE", "gamelists", "gba")
            os.makedirs(gamelist_dir)
            gamelist_path = os.path.join(gamelist_dir, "gamelist.xml")
            with open(gamelist_path, "w") as f:
                f.write(SAMPLE_GAMELIST_NO_OVERRIDE)

            es_de_config.set_system_override(tmpdir, "gba", "gpSP")

            # Override should be set
            result = es_de_config.get_system_override(tmpdir, "gba")
            assert result == "gpSP"

            # Game entry should be preserved
            with open(gamelist_path, "r") as f:
                content = f.read()
            assert "some_game.gba" in content

    def test_clears_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # First set an override
            es_de_config.set_system_override(tmpdir, "gba", "gpSP")
            assert es_de_config.get_system_override(tmpdir, "gba") == "gpSP"

            # Clear it
            es_de_config.set_system_override(tmpdir, "gba", None)
            assert es_de_config.get_system_override(tmpdir, "gba") is None

    def test_replaces_existing_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gamelist_dir = os.path.join(tmpdir, "ES-DE", "gamelists", "gba")
            os.makedirs(gamelist_dir)
            gamelist_path = os.path.join(gamelist_dir, "gamelist.xml")
            with open(gamelist_path, "w") as f:
                f.write(SAMPLE_GAMELIST_WITH_OVERRIDE)

            es_de_config.set_system_override(tmpdir, "gba", "VBA-M")
            result = es_de_config.get_system_override(tmpdir, "gba")
            assert result == "VBA-M"


class TestSetGameOverride:
    def setup_method(self):
        es_de_config._reset_cache()

    def test_creates_new_game_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            es_de_config.set_game_override(tmpdir, "gba", "./Pokemon.gba", "gpSP")

            gamelist_path = os.path.join(tmpdir, "ES-DE", "gamelists", "gba", "gamelist.xml")
            with open(gamelist_path, "r") as f:
                content = f.read()
            assert "Pokemon.gba" in content
            assert "gpSP" in content
            assert "<altemulator>" in content

    def test_updates_existing_game_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gamelist_dir = os.path.join(tmpdir, "ES-DE", "gamelists", "gba")
            os.makedirs(gamelist_dir)
            gamelist_path = os.path.join(gamelist_dir, "gamelist.xml")
            with open(gamelist_path, "w") as f:
                f.write(SAMPLE_GAMELIST_NO_OVERRIDE)

            es_de_config.set_game_override(tmpdir, "gba", "./some_game.gba", "gpSP")

            with open(gamelist_path, "r") as f:
                content = f.read()
            assert "gpSP" in content
            assert "Some Game" in content  # preserved

    def test_clears_game_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Set an override
            es_de_config.set_game_override(tmpdir, "gba", "./Pokemon.gba", "gpSP")

            gamelist_path = os.path.join(tmpdir, "ES-DE", "gamelists", "gba", "gamelist.xml")
            with open(gamelist_path, "r") as f:
                content = f.read()
            assert "<altemulator>" in content

            # Clear it
            es_de_config.set_game_override(tmpdir, "gba", "./Pokemon.gba", None)

            with open(gamelist_path, "r") as f:
                content = f.read()
            assert "<altemulator>" not in content
            assert "Pokemon.gba" in content  # game entry still there

    def test_preserves_system_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Set system override first
            es_de_config.set_system_override(tmpdir, "gba", "VBA-M")

            # Set per-game override
            es_de_config.set_game_override(tmpdir, "gba", "./Pokemon.gba", "gpSP")

            # System override should still be there
            result = es_de_config.get_system_override(tmpdir, "gba")
            assert result == "VBA-M"

            gamelist_path = os.path.join(tmpdir, "ES-DE", "gamelists", "gba", "gamelist.xml")
            with open(gamelist_path, "r") as f:
                content = f.read()
            assert "gpSP" in content
            assert "VBA-M" in content

    def test_round_trip_write_then_read(self):
        """Write system + game overrides, then read them back."""
        with tempfile.TemporaryDirectory() as tmpdir:
            es_de_config.set_system_override(tmpdir, "gba", "VBA-M")
            es_de_config.set_game_override(tmpdir, "gba", "./Pokemon.gba", "gpSP")
            es_de_config.set_game_override(tmpdir, "gba", "./Zelda.gba", "mGBA")

            # Read system override
            assert es_de_config.get_system_override(tmpdir, "gba") == "VBA-M"

            # Read gamelist — should have both games
            gamelist_path = os.path.join(tmpdir, "ES-DE", "gamelists", "gba", "gamelist.xml")
            with open(gamelist_path, "r") as f:
                content = f.read()
            assert "Pokemon.gba" in content
            assert "Zelda.gba" in content
            assert "gpSP" in content
            assert "mGBA" in content
