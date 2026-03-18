"""Tests for domain.bios.format_bios_status."""

from domain.bios import format_bios_status


class TestFormatBiosStatusFullDict:
    """Test with a fully-populated bios dict."""

    def test_all_fields_mapped_correctly(self):
        """All fields from a full bios dict are mapped to the frontend-ready dict."""
        bios = {
            "server_count": 3,
            "local_count": 2,
            "all_downloaded": False,
            "required_count": 2,
            "required_downloaded": 1,
            "files": [{"file_name": "gba_bios.bin", "downloaded": True}],
            "active_core": "mgba_libretro.so",
            "active_core_label": "mGBA",
            "available_cores": [{"core": "mgba_libretro.so", "label": "mGBA"}],
        }
        result = format_bios_status(bios, "gba")

        assert result["platform_slug"] == "gba"
        assert result["total"] == 3
        assert result["downloaded"] == 2
        assert result["all_downloaded"] is False
        assert result["required_count"] == 2
        assert result["required_downloaded"] == 1
        assert len(result["files"]) == 1
        assert result["files"][0]["file_name"] == "gba_bios.bin"
        assert result["active_core"] == "mgba_libretro.so"
        assert result["active_core_label"] == "mGBA"
        assert len(result["available_cores"]) == 1

    def test_platform_slug_passed_through(self):
        """platform_slug comes from the argument, not the bios dict."""
        bios = {"server_count": 1, "local_count": 1, "all_downloaded": True}
        result = format_bios_status(bios, "snes")
        assert result["platform_slug"] == "snes"

    def test_all_downloaded_true(self):
        """all_downloaded=True is preserved."""
        bios = {"all_downloaded": True, "server_count": 2, "local_count": 2}
        result = format_bios_status(bios, "psx")
        assert result["all_downloaded"] is True


class TestFormatBiosStatusMinimalDict:
    """Test with a minimal/empty bios dict — verify defaults."""

    def test_empty_dict_returns_defaults(self):
        """Missing optional fields fall back to defaults."""
        result = format_bios_status({}, "n64")

        assert result["platform_slug"] == "n64"
        assert result["total"] == 0
        assert result["downloaded"] == 0
        assert result["all_downloaded"] is False
        assert result["required_count"] is None
        assert result["required_downloaded"] is None
        assert result["files"] == []
        assert result["active_core"] is None
        assert result["active_core_label"] is None
        assert result["available_cores"] == []

    def test_partial_dict_uses_provided_values(self):
        """Only provided keys are used; missing ones use defaults."""
        bios = {"server_count": 5, "local_count": 3}
        result = format_bios_status(bios, "gba")

        assert result["total"] == 5
        assert result["downloaded"] == 3
        assert result["required_count"] is None
        assert result["files"] == []

    def test_none_values_not_substituted(self):
        """Explicit None values in bios dict are returned as-is for optional fields."""
        bios = {"required_count": None, "required_downloaded": None}
        result = format_bios_status(bios, "gba")
        assert result["required_count"] is None
        assert result["required_downloaded"] is None


class TestFormatBiosStatusNeedsBiosContext:
    """Test that the function is caller-agnostic about needs_bios."""

    def test_function_formats_regardless_of_needs_bios(self):
        """format_bios_status does not check needs_bios — caller decides when to call it."""
        bios = {
            "needs_bios": False,
            "server_count": 0,
            "local_count": 0,
        }
        result = format_bios_status(bios, "gb")
        # Result is still returned — caller is responsible for the needs_bios guard
        assert result["platform_slug"] == "gb"
        assert result["total"] == 0

    def test_needs_bios_key_not_in_output(self):
        """needs_bios is not included in the returned dict."""
        bios = {"needs_bios": True, "server_count": 1}
        result = format_bios_status(bios, "gba")
        assert "needs_bios" not in result
