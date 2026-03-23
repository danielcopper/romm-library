"""Tests for py_modules/domain/save_path.py"""

from __future__ import annotations

from domain.save_path import (
    detect_path_change,
    resolve_save_dir,
    resolve_save_filename,
)

# ---------------------------------------------------------------------------
# resolve_save_dir
# ---------------------------------------------------------------------------


class TestResolveSaveDir:
    SAVES_BASE = "/saves"

    def test_sort_by_content_simple_rom_path(self) -> None:
        """gba/Game.gba → last folder is 'gba' → saves/gba"""
        result = resolve_save_dir(
            rom_path="gba/Game.gba",
            saves_base=self.SAVES_BASE,
            system="gba",
            sort_by_content=True,
        )
        assert result == "/saves/gba"

    def test_sort_by_content_rom_in_subfolder(self) -> None:
        """psx/Game (USA)/Game.m3u → last folder is 'Game (USA)' → saves/Game (USA)"""
        result = resolve_save_dir(
            rom_path="psx/Game (USA)/Game.m3u",
            saves_base=self.SAVES_BASE,
            system="psx",
            sort_by_content=True,
        )
        assert result == "/saves/Game (USA)"

    def test_sort_by_content_false_flat(self) -> None:
        """sort_by_content=False → just saves_base, no subdir"""
        result = resolve_save_dir(
            rom_path="gba/Game.gba",
            saves_base=self.SAVES_BASE,
            system="gba",
            sort_by_content=False,
        )
        assert result == "/saves"

    def test_sort_by_core_adds_core_subdir(self) -> None:
        """sort_by_content=True + sort_by_core=True → saves/gba/mgba_libretro"""
        result = resolve_save_dir(
            rom_path="gba/Game.gba",
            saves_base=self.SAVES_BASE,
            system="gba",
            sort_by_content=True,
            sort_by_core=True,
            core_name="mgba_libretro",
        )
        assert result == "/saves/gba/mgba_libretro"

    def test_sort_by_content_and_sort_by_core_together(self) -> None:
        """Both flags True → saves/{content_dir}/{core}"""
        result = resolve_save_dir(
            rom_path="snes/Zelda.sfc",
            saves_base=self.SAVES_BASE,
            system="snes",
            sort_by_content=True,
            sort_by_core=True,
            core_name="snes9x_libretro",
        )
        assert result == "/saves/snes/snes9x_libretro"

    def test_sort_by_core_without_core_name_ignored(self) -> None:
        """sort_by_core=True but core_name=None → no core subdir added"""
        result = resolve_save_dir(
            rom_path="gba/Game.gba",
            saves_base=self.SAVES_BASE,
            system="gba",
            sort_by_content=True,
            sort_by_core=True,
            core_name=None,
        )
        assert result == "/saves/gba"

    def test_sort_by_content_uses_last_folder_not_system(self) -> None:
        """When last folder differs from system slug, last folder wins."""
        result = resolve_save_dir(
            rom_path="psx/Crash (Europe)/Crash.m3u",
            saves_base="/home/user/saves",
            system="psx",
            sort_by_content=True,
        )
        assert result == "/home/user/saves/Crash (Europe)"

    def test_flat_with_sort_by_core_and_core_name(self) -> None:
        """sort_by_content=False + sort_by_core=True → saves/{core} (no content subdir)"""
        result = resolve_save_dir(
            rom_path="gba/Game.gba",
            saves_base=self.SAVES_BASE,
            system="gba",
            sort_by_content=False,
            sort_by_core=True,
            core_name="mgba_libretro",
        )
        assert result == "/saves/mgba_libretro"


# ---------------------------------------------------------------------------
# resolve_save_filename
# ---------------------------------------------------------------------------


class TestResolveSaveFilename:
    def test_basic_rom_path(self) -> None:
        """gba/Pokemon.gba → Pokemon.srm"""
        assert resolve_save_filename("gba/Pokemon.gba") == "Pokemon.srm"

    def test_default_extension_is_srm(self) -> None:
        assert resolve_save_filename("snes/Zelda.sfc") == "Zelda.srm"

    def test_custom_extension(self) -> None:
        assert resolve_save_filename("gba/Game.gba", ext=".sav") == "Game.sav"

    def test_spaces_in_name(self) -> None:
        assert resolve_save_filename("psx/Crash Bandicoot (USA).bin") == "Crash Bandicoot (USA).srm"

    def test_m3u_strips_m3u_extension(self) -> None:
        """m3u playlists: strip .m3u, keep base name"""
        assert resolve_save_filename("psx/Game (USA)/Game (USA).m3u") == "Game (USA).srm"

    def test_rom_without_subdir(self) -> None:
        """ROM path with no directory component"""
        assert resolve_save_filename("Game.gba") == "Game.srm"


# ---------------------------------------------------------------------------
# detect_path_change
# ---------------------------------------------------------------------------


class TestDetectPathChange:
    def test_same_path_returns_false(self) -> None:
        assert detect_path_change("/saves/gba", "/saves/gba") is False

    def test_different_path_returns_true(self) -> None:
        assert detect_path_change("/saves/gba", "/saves/Game (USA)") is True

    def test_none_stored_returns_true(self) -> None:
        """First sync — no stored path yet → treat as changed."""
        assert detect_path_change(None, "/saves/gba") is True

    def test_trailing_slash_difference(self) -> None:
        """Paths with vs without trailing slash are different strings."""
        assert detect_path_change("/saves/gba/", "/saves/gba") is True
