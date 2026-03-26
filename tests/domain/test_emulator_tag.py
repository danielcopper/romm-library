"""Unit tests for domain.emulator_tag — pure emulator tag construction functions."""

from __future__ import annotations

from domain.emulator_tag import build_emulator_tag, detect_core_change

# ---------------------------------------------------------------------------
# TestBuildEmulatorTag
# ---------------------------------------------------------------------------


class TestBuildEmulatorTag:
    def test_normal_core_strips_libretro_suffix(self):
        assert build_emulator_tag("mgba_libretro") == "retroarch-mgba"

    def test_core_with_digits_strips_libretro_suffix(self):
        assert build_emulator_tag("snes9x_libretro") == "retroarch-snes9x"

    def test_swanstation_core(self):
        assert build_emulator_tag("swanstation_libretro") == "retroarch-swanstation"

    def test_none_input_returns_fallback(self):
        assert build_emulator_tag(None) == "retroarch"

    def test_empty_string_returns_fallback(self):
        assert build_emulator_tag("") == "retroarch"

    def test_core_without_libretro_suffix_passes_through(self):
        # Shouldn't happen in practice but must not crash
        assert build_emulator_tag("mgba") == "retroarch-mgba"

    def test_uppercase_core_is_lowercased(self):
        assert build_emulator_tag("MGBA_libretro") == "retroarch-mgba"


# ---------------------------------------------------------------------------
# TestDetectCoreChange
# ---------------------------------------------------------------------------


class TestDetectCoreChange:
    def test_same_core_returns_false(self):
        assert detect_core_change("mgba_libretro", "mgba_libretro") is False

    def test_different_cores_returns_true(self):
        assert detect_core_change("mgba_libretro", "snes9x_libretro") is True

    def test_stored_none_returns_false(self):
        # First sync — no prior core recorded, can't determine change
        assert detect_core_change(None, "mgba_libretro") is False

    def test_active_none_returns_false(self):
        # Core unresolved — can't determine change
        assert detect_core_change("mgba_libretro", None) is False

    def test_both_none_returns_false(self):
        assert detect_core_change(None, None) is False
