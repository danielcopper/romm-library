"""Tests for models.bios dataclasses."""

from dataclasses import asdict

from models.bios import AvailableCore, BiosFileEntry, BiosStatus


class TestAvailableCore:
    def test_construction(self):
        core = AvailableCore(core_so="mgba_libretro.so", label="mGBA", is_default=True)
        assert core.core_so == "mgba_libretro.so"
        assert core.label == "mGBA"
        assert core.is_default is True

    def test_frozen(self):
        core = AvailableCore(core_so="mgba_libretro.so", label="mGBA", is_default=True)
        try:
            core.label = "other"  # type: ignore[misc]
            raise AssertionError("Should have raised AttributeError")
        except AttributeError:
            pass

    def test_asdict(self):
        core = AvailableCore(core_so="mgba_libretro.so", label="mGBA", is_default=True)
        d = asdict(core)
        assert d == {"core_so": "mgba_libretro.so", "label": "mGBA", "is_default": True}


class TestBiosFileEntry:
    def test_construction(self):
        entry = BiosFileEntry(
            file_name="gba_bios.bin",
            downloaded=True,
            local_path="/bios/gba_bios.bin",
            required=True,
            description="GBA BIOS",
            classification="required",
            cores={"mgba_libretro.so": {"required": True}},
            used_by_active=True,
        )
        assert entry.file_name == "gba_bios.bin"
        assert entry.downloaded is True
        assert entry.classification == "required"

    def test_asdict(self):
        entry = BiosFileEntry(
            file_name="gba_bios.bin",
            downloaded=False,
            local_path="/bios/gba_bios.bin",
            required=False,
            description="GBA BIOS",
            classification="optional",
            cores={},
            used_by_active=False,
        )
        d = asdict(entry)
        assert d["file_name"] == "gba_bios.bin"
        assert d["downloaded"] is False
        assert d["cores"] == {}


class TestBiosStatus:
    def _make_status(self, **overrides):
        defaults = {
            "platform_slug": "gba",
            "total": 3,
            "downloaded": 2,
            "all_downloaded": False,
            "required_count": 2,
            "required_downloaded": 1,
            "files": (),
            "active_core": "mgba_libretro.so",
            "active_core_label": "mGBA",
            "available_cores": (),
        }
        defaults.update(overrides)
        return BiosStatus(**defaults)

    def test_construction(self):
        status = self._make_status()
        assert status.platform_slug == "gba"
        assert status.total == 3
        assert status.cached_at == 0.0

    def test_cached_at_override(self):
        status = self._make_status(cached_at=1234.5)
        assert status.cached_at == 1234.5

    def test_none_optional_fields(self):
        status = self._make_status(required_count=None, required_downloaded=None, active_core=None)
        assert status.required_count is None
        assert status.active_core is None

    def test_asdict_roundtrip(self):
        core = AvailableCore(core_so="mgba_libretro.so", label="mGBA", is_default=True)
        file_entry = BiosFileEntry(
            file_name="gba_bios.bin",
            downloaded=True,
            local_path="/bios/gba_bios.bin",
            required=True,
            description="GBA BIOS",
            classification="required",
            cores={"mgba_libretro.so": {"required": True}},
            used_by_active=True,
        )
        status = self._make_status(files=(file_entry,), available_cores=(core,))
        d = asdict(status)
        assert d["platform_slug"] == "gba"
        assert len(d["files"]) == 1
        assert d["files"][0]["file_name"] == "gba_bios.bin"
        assert len(d["available_cores"]) == 1
        assert d["available_cores"][0]["core_so"] == "mgba_libretro.so"
