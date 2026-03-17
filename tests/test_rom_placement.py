"""Tests for services/rom_placement.py — WiiU file placement logic."""

import logging
import os
import tempfile
from unittest.mock import patch

from services.rom_placement import (
    PLATFORM_PLACEMENT,
    _default_placement,
    get_placement,
    place_wiiu,
)

_logger = logging.getLogger("test_rom_placement")


# ---------------------------------------------------------------------------
# get_placement registry
# ---------------------------------------------------------------------------


def test_get_placement_wiiu():
    fn = get_placement("wiiu")
    assert fn is place_wiiu


def test_get_placement_unknown_returns_default():
    fn = get_placement("snes")
    assert fn is _default_placement


def test_get_placement_empty_string_returns_default():
    fn = get_placement("")
    assert fn is _default_placement


# ---------------------------------------------------------------------------
# _default_placement
# ---------------------------------------------------------------------------


def test_default_placement_is_noop():
    with tempfile.TemporaryDirectory() as rom_dir:
        sentinel = os.path.join(rom_dir, "game.rom")
        open(sentinel, "w").close()
        _default_placement(rom_dir, ["game.rom"], _logger)
        # file untouched
        assert os.path.exists(sentinel)


# ---------------------------------------------------------------------------
# place_wiiu — happy paths
# ---------------------------------------------------------------------------


def test_place_wiiu_moves_update_folder():
    with tempfile.TemporaryDirectory() as rom_dir, tempfile.TemporaryDirectory() as bios_dir:
        folder_name = "Zelda BotW [Update] [00050000101c9400]"
        folder_path = os.path.join(rom_dir, folder_name)
        os.makedirs(folder_path)
        content_file = os.path.join(folder_path, "update.bin")
        open(content_file, "w").close()

        with patch("services.rom_placement.retrodeck_config.get_bios_path", return_value=bios_dir):
            place_wiiu(rom_dir, [], _logger)

        expected_dest = os.path.join(bios_dir, "cemu", "mlc01", "usr", "title", "0005000e", "00050000101c9400")
        assert os.path.exists(os.path.join(expected_dest, "update.bin"))
        assert not os.path.exists(folder_path)


def test_place_wiiu_moves_dlc_folder():
    with tempfile.TemporaryDirectory() as rom_dir, tempfile.TemporaryDirectory() as bios_dir:
        folder_name = "Zelda BotW [DLC] [00050000101c9400]"
        folder_path = os.path.join(rom_dir, folder_name)
        os.makedirs(folder_path)
        dlc_file = os.path.join(folder_path, "dlc.bin")
        open(dlc_file, "w").close()

        with patch("services.rom_placement.retrodeck_config.get_bios_path", return_value=bios_dir):
            place_wiiu(rom_dir, [], _logger)

        expected_dest = os.path.join(bios_dir, "cemu", "mlc01", "usr", "title", "0005000c", "00050000101c9400")
        assert os.path.exists(os.path.join(expected_dest, "dlc.bin"))
        assert not os.path.exists(folder_path)


def test_place_wiiu_keeps_game_folder():
    with tempfile.TemporaryDirectory() as rom_dir, tempfile.TemporaryDirectory() as bios_dir:
        folder_name = "Zelda BotW [Game] [00050000101c9400]"
        folder_path = os.path.join(rom_dir, folder_name)
        os.makedirs(folder_path)
        game_file = os.path.join(folder_path, "game.bin")
        open(game_file, "w").close()

        with patch("services.rom_placement.retrodeck_config.get_bios_path", return_value=bios_dir):
            place_wiiu(rom_dir, [], _logger)

        # Game folder must remain in rom_dir
        assert os.path.exists(folder_path)
        assert os.path.exists(game_file)


def test_place_wiiu_no_matching_folders():
    with tempfile.TemporaryDirectory() as rom_dir, tempfile.TemporaryDirectory() as bios_dir:
        # No WiiU-format folders
        other = os.path.join(rom_dir, "some_random_folder")
        os.makedirs(other)

        with patch("services.rom_placement.retrodeck_config.get_bios_path", return_value=bios_dir):
            place_wiiu(rom_dir, [], _logger)

        assert os.path.exists(other)


def test_place_wiiu_creates_target_dirs():
    with tempfile.TemporaryDirectory() as rom_dir, tempfile.TemporaryDirectory() as bios_dir:
        folder_name = "Game [Update] [aabbccdd11223344]"
        os.makedirs(os.path.join(rom_dir, folder_name))

        expected_dest = os.path.join(bios_dir, "cemu", "mlc01", "usr", "title", "0005000e", "aabbccdd11223344")
        assert not os.path.exists(expected_dest)

        with patch("services.rom_placement.retrodeck_config.get_bios_path", return_value=bios_dir):
            place_wiiu(rom_dir, [], _logger)

        assert os.path.isdir(expected_dest)


def test_place_wiiu_title_id_lowercased():
    with tempfile.TemporaryDirectory() as rom_dir, tempfile.TemporaryDirectory() as bios_dir:
        folder_name = "Game [Update] [AABBCCDD11223344]"
        os.makedirs(os.path.join(rom_dir, folder_name))

        with patch("services.rom_placement.retrodeck_config.get_bios_path", return_value=bios_dir):
            place_wiiu(rom_dir, [], _logger)

        expected_dest = os.path.join(bios_dir, "cemu", "mlc01", "usr", "title", "0005000e", "aabbccdd11223344")
        assert os.path.isdir(expected_dest)


# ---------------------------------------------------------------------------
# place_wiiu — edge / bad paths
# ---------------------------------------------------------------------------


def test_place_wiiu_no_bios_path(caplog):
    with tempfile.TemporaryDirectory() as rom_dir:
        with patch("services.rom_placement.retrodeck_config.get_bios_path", return_value=None):
            with caplog.at_level(logging.WARNING):
                place_wiiu(rom_dir, [], _logger)
        assert "bios path not available" in caplog.text


def test_place_wiiu_empty_bios_path_string(caplog):
    with tempfile.TemporaryDirectory() as rom_dir:
        with patch("services.rom_placement.retrodeck_config.get_bios_path", return_value=""):
            with caplog.at_level(logging.WARNING):
                place_wiiu(rom_dir, [], _logger)
        assert "bios path not available" in caplog.text


def test_place_wiiu_rom_dir_does_not_exist(caplog):
    with tempfile.TemporaryDirectory() as bios_dir:
        nonexistent = "/tmp/does_not_exist_rom_placement_test"
        with patch("services.rom_placement.retrodeck_config.get_bios_path", return_value=bios_dir):
            with caplog.at_level(logging.WARNING):
                place_wiiu(nonexistent, [], _logger)
        assert "cannot list rom_dir" in caplog.text


def test_place_wiiu_skips_files_not_dirs():
    with tempfile.TemporaryDirectory() as rom_dir, tempfile.TemporaryDirectory() as bios_dir:
        # A file (not a dir) with matching name — should be skipped
        fake_file = os.path.join(rom_dir, "Game [Update] [00050000101c9400]")
        open(fake_file, "w").close()

        with patch("services.rom_placement.retrodeck_config.get_bios_path", return_value=bios_dir):
            place_wiiu(rom_dir, [], _logger)

        # file should remain untouched
        assert os.path.exists(fake_file)


def test_place_wiiu_multiple_titles():
    with tempfile.TemporaryDirectory() as rom_dir, tempfile.TemporaryDirectory() as bios_dir:
        game_folder = os.path.join(rom_dir, "Game A [Game] [aaaa000000000001]")
        update_folder = os.path.join(rom_dir, "Game A [Update] [aaaa000000000001]")
        dlc_folder = os.path.join(rom_dir, "Game A [DLC] [aaaa000000000001]")
        os.makedirs(game_folder)
        os.makedirs(update_folder)
        os.makedirs(dlc_folder)

        with patch("services.rom_placement.retrodeck_config.get_bios_path", return_value=bios_dir):
            place_wiiu(rom_dir, [], _logger)

        # Game stays
        assert os.path.isdir(game_folder)
        # Update moved
        assert not os.path.exists(update_folder)
        assert os.path.isdir(os.path.join(bios_dir, "cemu", "mlc01", "usr", "title", "0005000e", "aaaa000000000001"))
        # DLC moved
        assert not os.path.exists(dlc_folder)
        assert os.path.isdir(os.path.join(bios_dir, "cemu", "mlc01", "usr", "title", "0005000c", "aaaa000000000001"))


# ---------------------------------------------------------------------------
# PLATFORM_PLACEMENT registry sanity
# ---------------------------------------------------------------------------


def test_platform_placement_registry_contains_wiiu():
    assert "wiiu" in PLATFORM_PLACEMENT
    assert PLATFORM_PLACEMENT["wiiu"] is place_wiiu
