"""Tests for domain.save_extensions pure functions."""

from __future__ import annotations

from unittest.mock import patch

from domain.save_extensions import get_all_known_extensions, get_save_extensions


class TestGetSaveExtensionsDefault:
    """get_save_extensions returns defaults when no override exists."""

    def test_no_argument_returns_default(self):
        """Calling with no argument returns the default extensions."""
        result = get_save_extensions()
        assert result == (".srm", ".rtc")

    def test_none_argument_returns_default(self):
        """Passing None explicitly returns the default extensions."""
        result = get_save_extensions(None)
        assert result == (".srm", ".rtc")

    def test_known_platform_without_override_returns_default(self):
        """A real platform slug with no override returns the default."""
        result = get_save_extensions("gba")
        assert result == (".srm", ".rtc")

    def test_unknown_platform_returns_default(self):
        """An unrecognised platform slug returns the default."""
        result = get_save_extensions("unknown_platform")
        assert result == (".srm", ".rtc")


class TestGetSaveExtensionsWithOverride:
    """get_save_extensions respects platform-specific overrides."""

    _N64_EXTS = (".srm", ".rtc", ".eep", ".sra", ".fla", ".mpk")

    def test_override_platform_returns_override(self):
        """A platform with an override returns that override instead of the default."""
        with patch(
            "domain.save_extensions._PLATFORM_OVERRIDES",
            {"n64": self._N64_EXTS},
        ):
            result = get_save_extensions("n64")
            assert result == self._N64_EXTS

    def test_non_override_platform_still_returns_default(self):
        """Other platforms are unaffected when an override is present for a different one."""
        with patch(
            "domain.save_extensions._PLATFORM_OVERRIDES",
            {"n64": self._N64_EXTS},
        ):
            result = get_save_extensions("gba")
            assert result == (".srm", ".rtc")


class TestGetAllKnownExtensions:
    """get_all_known_extensions covers defaults and all override extensions."""

    def test_contains_default_extensions(self):
        """Result always contains the default .srm and .rtc extensions."""
        result = get_all_known_extensions()
        assert ".srm" in result
        assert ".rtc" in result

    def test_returns_tuple(self):
        """Result is a tuple (immutable)."""
        assert isinstance(get_all_known_extensions(), tuple)

    def test_with_patched_override_includes_override_extensions(self):
        """Override extensions appear in the combined result."""
        overrides = {"n64": (".srm", ".rtc", ".eep", ".mpk")}
        with patch("domain.save_extensions._PLATFORM_OVERRIDES", overrides):
            result = get_all_known_extensions()
            assert ".eep" in result
            assert ".mpk" in result

    def test_no_duplicates_when_override_repeats_defaults(self):
        """Extensions shared between defaults and overrides are not duplicated."""
        overrides = {"n64": (".srm", ".rtc", ".eep")}
        with patch("domain.save_extensions._PLATFORM_OVERRIDES", overrides):
            result = get_all_known_extensions()
            assert result.count(".srm") == 1
            assert result.count(".rtc") == 1
            assert result.count(".eep") == 1

    def test_no_duplicates_across_multiple_overrides(self):
        """Extensions shared across multiple platform overrides appear only once."""
        overrides = {
            "n64": (".srm", ".eep"),
            "gba": (".srm", ".sav"),
        }
        with patch("domain.save_extensions._PLATFORM_OVERRIDES", overrides):
            result = get_all_known_extensions()
            assert result.count(".srm") == 1
            assert ".eep" in result
            assert ".sav" in result
