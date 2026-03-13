"""Tests for SaveSyncService with FakeSaveApi (no HTTP, no mocking)."""

import asyncio
import hashlib
import logging

import pytest
from fakes.fake_save_api import FakeSaveApi
from services.save_sync import SaveSyncService

from lib.errors import RommApiError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _no_retry(fn, *a, **kw):
    return fn(*a, **kw)


def make_service(tmp_path, fake_api=None, **overrides):
    """Create a SaveSyncService with sensible defaults for testing."""
    fake = fake_api or FakeSaveApi()
    defaults = dict(
        save_api=fake,
        with_retry=_no_retry,
        is_retryable=lambda e: False,
        state={"shortcut_registry": {}, "installed_roms": {}},
        save_sync_state=SaveSyncService.make_default_state(),
        loop=asyncio.get_event_loop(),
        logger=logging.getLogger("test"),
        runtime_dir=str(tmp_path),
        get_saves_path=lambda: str(tmp_path / "saves"),
    )
    defaults.update(overrides)
    svc = SaveSyncService(**defaults)
    svc.init_state()
    return svc, defaults.get("save_api", fake) if fake_api is None else fake


def _install_rom(svc, tmp_path, rom_id=42, system="gba", file_name="pokemon.gba"):
    """Register a ROM in installed_roms state."""
    svc._state["installed_roms"][str(rom_id)] = {
        "rom_id": rom_id,
        "file_name": file_name,
        "file_path": str(tmp_path / "retrodeck" / "roms" / system / file_name),
        "system": system,
        "platform_slug": system,
        "installed_at": "2026-01-01T00:00:00",
    }


def _create_save(tmp_path, system="gba", rom_name="pokemon", content=b"\x00" * 1024, ext=".srm"):
    """Create a save file on disk and return its path."""
    saves_dir = tmp_path / "saves" / system
    saves_dir.mkdir(parents=True, exist_ok=True)
    save_file = saves_dir / (rom_name + ext)
    save_file.write_bytes(content)
    return save_file


def _server_save(
    save_id=100, rom_id=42, filename="pokemon.srm", updated_at="2026-02-17T06:00:00Z", file_size_bytes=1024
):
    return {
        "id": save_id,
        "rom_id": rom_id,
        "file_name": filename,
        "updated_at": updated_at,
        "file_size_bytes": file_size_bytes,
        "emulator": "retroarch",
        "download_path": f"/saves/{filename}",
    }


def _file_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# TestStateManagement
# ---------------------------------------------------------------------------


class TestStateManagement:
    def test_make_default_state(self):
        state = SaveSyncService.make_default_state()
        assert state["device_id"] is None
        assert state["saves"] == {}
        assert state["settings"]["save_sync_enabled"] is False

    def test_init_state_populates_defaults(self, tmp_path):
        svc, _ = make_service(tmp_path, save_sync_state={})
        assert svc._save_sync_state["settings"]["conflict_mode"] == "ask_me"
        assert svc._save_sync_state["saves"] == {}

    def test_init_state_preserves_existing(self, tmp_path):
        state = SaveSyncService.make_default_state()
        state["device_id"] = "existing-id"
        svc, _ = make_service(tmp_path, save_sync_state=state)
        assert svc._save_sync_state["device_id"] == "existing-id"

    def test_save_and_load_state(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["device_id"] = "test-device"
        svc._save_sync_state["saves"]["42"] = {"files": {}}
        svc.save_state()

        # Load into a fresh service
        svc2, _ = make_service(tmp_path)
        svc2.load_state()
        assert svc2._save_sync_state["device_id"] == "test-device"
        assert "42" in svc2._save_sync_state["saves"]

    def test_load_state_missing_file(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc.load_state()  # should not raise
        assert svc._save_sync_state["device_id"] is None

    def test_prune_orphaned_state(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["saves"]["99"] = {"files": {}}
        svc._save_sync_state["playtime"]["99"] = {"total_seconds": 100}
        svc._state["shortcut_registry"]["42"] = {}

        svc.prune_orphaned_state()
        assert "99" not in svc._save_sync_state["saves"]
        assert "99" not in svc._save_sync_state["playtime"]

    def test_prune_keeps_registered(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["saves"]["42"] = {"files": {}}
        svc._state["shortcut_registry"]["42"] = {}

        svc.prune_orphaned_state()
        assert "42" in svc._save_sync_state["saves"]


# ---------------------------------------------------------------------------
# TestDeviceRegistration
# ---------------------------------------------------------------------------


class TestDeviceRegistration:
    @pytest.mark.asyncio
    async def test_registers_new_device(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True

        result = await svc.ensure_device_registered()
        assert result["success"] is True
        assert result["device_id"]
        assert result["device_name"]
        # Persisted
        assert svc._save_sync_state["device_id"] == result["device_id"]

    @pytest.mark.asyncio
    async def test_returns_existing_device(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        svc._save_sync_state["device_id"] = "existing"
        svc._save_sync_state["device_name"] = "deck"

        result = await svc.ensure_device_registered()
        assert result["device_id"] == "existing"
        assert result["device_name"] == "deck"

    @pytest.mark.asyncio
    async def test_disabled_returns_failure(self, tmp_path):
        svc, _ = make_service(tmp_path)
        # save_sync_enabled defaults to False
        result = await svc.ensure_device_registered()
        assert result["success"] is False
        assert result.get("disabled") is True


# ---------------------------------------------------------------------------
# TestConflictDetection
# ---------------------------------------------------------------------------


class TestConflictDetection:
    def test_skip_when_unchanged(self, tmp_path):
        svc, fake = make_service(tmp_path)
        content = b"save data"
        local_hash = hashlib.md5(content).hexdigest()

        svc._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": local_hash,
                    "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
                    "last_sync_server_size": 1024,
                }
            }
        }

        server = _server_save()
        result = svc._detect_conflict(42, "pokemon.srm", local_hash, server)
        assert result == "skip"

    def test_upload_when_local_changed(self, tmp_path):
        svc, fake = make_service(tmp_path)
        old_hash = hashlib.md5(b"old").hexdigest()
        new_hash = hashlib.md5(b"new data").hexdigest()

        svc._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": old_hash,
                    "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
                    "last_sync_server_size": 1024,
                }
            }
        }

        server = _server_save()
        result = svc._detect_conflict(42, "pokemon.srm", new_hash, server)
        assert result == "upload"

    def test_download_when_server_changed(self, tmp_path):
        svc, fake = make_service(tmp_path)
        local_hash = hashlib.md5(b"save data").hexdigest()

        svc._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": local_hash,
                    "last_sync_server_updated_at": "2026-02-17T04:00:00Z",
                    "last_sync_server_size": 1024,
                }
            }
        }

        # Server has a different updated_at, and downloading it yields a different hash
        server = _server_save(updated_at="2026-02-17T08:00:00Z", file_size_bytes=2048)
        # The slow path will download + hash. The fake will write default content.
        # We need the downloaded hash to differ from last_sync_hash.
        # Since FakeSaveApi.download_save writes 1024 zero bytes and local_hash is md5("save data"),
        # the server hash will naturally differ.
        result = svc._detect_conflict(42, "pokemon.srm", local_hash, server)
        assert result == "download"

    def test_conflict_when_both_changed(self, tmp_path):
        svc, fake = make_service(tmp_path)
        old_hash = hashlib.md5(b"baseline").hexdigest()
        new_local = hashlib.md5(b"local edit").hexdigest()

        svc._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": old_hash,
                    "last_sync_server_updated_at": "2026-02-17T04:00:00Z",
                    "last_sync_server_size": 1024,
                }
            }
        }

        server = _server_save(updated_at="2026-02-17T08:00:00Z", file_size_bytes=2048)
        result = svc._detect_conflict(42, "pokemon.srm", new_local, server)
        assert result == "conflict"

    def test_never_synced_same_hash_skips(self, tmp_path):
        """When never synced but local and server have same content -> skip."""
        svc, fake = make_service(tmp_path)
        # FakeSaveApi.download_save writes 1024 zero bytes
        content = b"\x00" * 1024
        local_hash = hashlib.md5(content).hexdigest()

        server = _server_save()
        result = svc._detect_conflict(42, "pokemon.srm", local_hash, server)
        assert result == "skip"

    def test_never_synced_different_hash_conflicts(self, tmp_path):
        """When never synced and hashes differ -> conflict."""
        svc, fake = make_service(tmp_path)
        local_hash = hashlib.md5(b"different content").hexdigest()

        server = _server_save()
        result = svc._detect_conflict(42, "pokemon.srm", local_hash, server)
        assert result == "conflict"


# ---------------------------------------------------------------------------
# TestConflictDetectionLightweight
# ---------------------------------------------------------------------------


class TestConflictDetectionLightweight:
    def test_skip_when_unchanged(self, tmp_path):
        svc, _ = make_service(tmp_path)
        file_state = {
            "last_sync_hash": "abc",
            "last_sync_local_mtime": 1000.0,
            "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
            "last_sync_server_size": 1024,
        }
        server = _server_save()
        result = svc._detect_conflict_lightweight(1000.0, 1024, server, file_state)
        assert result == "skip"

    def test_upload_local_only(self, tmp_path):
        svc, _ = make_service(tmp_path)
        file_state = {"last_sync_hash": "abc", "last_sync_local_mtime": 1000.0}
        result = svc._detect_conflict_lightweight(2000.0, 1024, None, file_state)
        assert result == "upload"

    def test_download_server_changed(self, tmp_path):
        svc, _ = make_service(tmp_path)
        file_state = {
            "last_sync_hash": "abc",
            "last_sync_local_mtime": 1000.0,
            "last_sync_server_updated_at": "2026-02-17T04:00:00Z",
            "last_sync_server_size": 1024,
        }
        server = _server_save(updated_at="2026-02-17T08:00:00Z")
        result = svc._detect_conflict_lightweight(1000.0, 1024, server, file_state)
        assert result == "download"

    def test_conflict_both_changed(self, tmp_path):
        svc, _ = make_service(tmp_path)
        file_state = {
            "last_sync_hash": "abc",
            "last_sync_local_mtime": 1000.0,
            "last_sync_server_updated_at": "2026-02-17T04:00:00Z",
            "last_sync_server_size": 1024,
        }
        server = _server_save(updated_at="2026-02-17T08:00:00Z")
        result = svc._detect_conflict_lightweight(2000.0, 1024, server, file_state)
        assert result == "conflict"

    def test_never_synced_no_server(self, tmp_path):
        svc, _ = make_service(tmp_path)
        result = svc._detect_conflict_lightweight(1000.0, 1024, None, {})
        assert result == "upload"

    def test_never_synced_with_server(self, tmp_path):
        svc, _ = make_service(tmp_path)
        server = _server_save()
        result = svc._detect_conflict_lightweight(1000.0, 1024, server, {})
        assert result == "conflict"


# ---------------------------------------------------------------------------
# TestSyncRomSaves
# ---------------------------------------------------------------------------


class TestSyncRomSaves:
    def test_local_only_uploads(self, tmp_path):
        svc, fake = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        _install_rom(svc, tmp_path)
        _create_save(tmp_path, content=b"save data")

        synced, errors, conflicts = svc._sync_rom_saves(42)
        assert synced == 1
        assert errors == []
        assert conflicts == []
        assert any(c[0] == "upload_save" for c in fake.call_log)

    def test_server_only_downloads(self, tmp_path):
        svc, fake = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        _install_rom(svc, tmp_path)
        # Add server save but no local file
        ss = _server_save()
        fake.saves[100] = ss

        synced, errors, conflicts = svc._sync_rom_saves(42)
        assert synced == 1
        assert errors == []
        # Verify the file was downloaded
        saves_dir = tmp_path / "saves" / "gba"
        assert (saves_dir / "pokemon.srm").exists()

    def test_matching_saves_skip(self, tmp_path):
        svc, fake = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        _install_rom(svc, tmp_path)
        save_path = _create_save(tmp_path)
        local_hash = _file_md5(str(save_path))

        ss = _server_save()
        fake.saves[100] = ss

        # Set sync state to match
        svc._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": local_hash,
                    "last_sync_server_updated_at": ss["updated_at"],
                    "last_sync_server_size": ss["file_size_bytes"],
                }
            }
        }

        synced, errors, conflicts = svc._sync_rom_saves(42)
        assert synced == 0
        assert errors == []
        assert conflicts == []

    def test_rom_not_installed(self, tmp_path):
        svc, _ = make_service(tmp_path)
        synced, errors, conflicts = svc._sync_rom_saves(999)
        assert synced == 0
        assert errors == []

    def test_api_error_on_list_saves(self, tmp_path):
        svc, fake = make_service(tmp_path)
        _install_rom(svc, tmp_path)
        fake.fail_on_next(RommApiError("Server error"))

        synced, errors, conflicts = svc._sync_rom_saves(42)
        assert synced == 0
        assert len(errors) == 1
        assert "Failed to fetch saves" in errors[0]


# ---------------------------------------------------------------------------
# TestSyncAllSaves
# ---------------------------------------------------------------------------


class TestSyncAllSaves:
    @pytest.mark.asyncio
    async def test_syncs_multiple_roms(self, tmp_path):
        svc, fake = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        svc._save_sync_state["device_id"] = "test-device"

        _install_rom(svc, tmp_path, rom_id=1, system="gba", file_name="game1.gba")
        _install_rom(svc, tmp_path, rom_id=2, system="snes", file_name="game2.sfc")
        _create_save(tmp_path, system="gba", rom_name="game1", content=b"save1")
        _create_save(tmp_path, system="snes", rom_name="game2", content=b"save2")

        result = await svc.sync_all_saves()
        assert result["success"] is True
        assert result["synced"] == 2
        assert result["roms_checked"] == 2

    @pytest.mark.asyncio
    async def test_disabled_returns_early(self, tmp_path):
        svc, _ = make_service(tmp_path)
        result = await svc.sync_all_saves()
        assert result["success"] is False
        assert "disabled" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_partial_failure(self, tmp_path):
        svc, fake = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        svc._save_sync_state["device_id"] = "test-device"

        _install_rom(svc, tmp_path, rom_id=1, system="gba", file_name="game1.gba")
        _install_rom(svc, tmp_path, rom_id=2, system="snes", file_name="game2.sfc")
        _create_save(tmp_path, system="gba", rom_name="game1", content=b"save1")
        _create_save(tmp_path, system="snes", rom_name="game2", content=b"save2")

        # Make the second ROM's list_saves fail
        original_list = fake.list_saves

        call_count = 0

        async def flaky_list(rom_id):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RommApiError("Server error")
            return await original_list(rom_id)

        fake.list_saves = flaky_list

        result = await svc.sync_all_saves()
        assert result["synced"] >= 1
        assert len(result["errors"]) >= 1


# ---------------------------------------------------------------------------
# TestPreLaunchSync
# ---------------------------------------------------------------------------


class TestPreLaunchSync:
    @pytest.mark.asyncio
    async def test_downloads_server_saves(self, tmp_path):
        svc, fake = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        svc._save_sync_state["device_id"] = "test-device"
        _install_rom(svc, tmp_path)

        ss = _server_save()
        fake.saves[100] = ss

        result = await svc.pre_launch_sync(42)
        assert result["success"] is True
        assert result["synced"] == 1

    @pytest.mark.asyncio
    async def test_disabled_skips(self, tmp_path):
        svc, _ = make_service(tmp_path)
        result = await svc.pre_launch_sync(42)
        assert result["success"] is True
        assert result["synced"] == 0

    @pytest.mark.asyncio
    async def test_pre_launch_disabled_in_settings(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        svc._save_sync_state["settings"]["sync_before_launch"] = False
        svc._save_sync_state["device_id"] = "test-device"

        result = await svc.pre_launch_sync(42)
        assert result["synced"] == 0


# ---------------------------------------------------------------------------
# TestPostExitSync
# ---------------------------------------------------------------------------


class TestPostExitSync:
    @pytest.mark.asyncio
    async def test_uploads_changed_saves(self, tmp_path):
        svc, fake = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        svc._save_sync_state["device_id"] = "test-device"
        _install_rom(svc, tmp_path)
        _create_save(tmp_path, content=b"new save data")

        result = await svc.post_exit_sync(42)
        assert result["success"] is True
        assert result["synced"] == 1

    @pytest.mark.asyncio
    async def test_disabled_skips(self, tmp_path):
        svc, _ = make_service(tmp_path)
        result = await svc.post_exit_sync(42)
        assert result["success"] is True
        assert result["synced"] == 0

    @pytest.mark.asyncio
    async def test_post_exit_disabled_in_settings(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        svc._save_sync_state["settings"]["sync_after_exit"] = False
        svc._save_sync_state["device_id"] = "test-device"

        result = await svc.post_exit_sync(42)
        assert result["synced"] == 0

    @pytest.mark.asyncio
    async def test_auto_registers_device(self, tmp_path):
        svc, fake = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        # No device_id set
        _install_rom(svc, tmp_path)
        _create_save(tmp_path, content=b"data")

        result = await svc.post_exit_sync(42)
        assert result["success"] is True
        assert svc._save_sync_state["device_id"] is not None


# ---------------------------------------------------------------------------
# TestResolveConflict
# ---------------------------------------------------------------------------


class TestResolveConflict:
    @pytest.mark.asyncio
    async def test_download_resolution(self, tmp_path):
        svc, fake = make_service(tmp_path)
        _install_rom(svc, tmp_path)

        ss = _server_save()
        fake.saves[100] = ss

        result = await svc.resolve_conflict(
            rom_id=42,
            filename="pokemon.srm",
            resolution="download",
            server_save_id=100,
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_upload_resolution(self, tmp_path):
        svc, fake = make_service(tmp_path)
        _install_rom(svc, tmp_path)
        save_path = _create_save(tmp_path)

        ss = _server_save()
        fake.saves[100] = ss

        result = await svc.resolve_conflict(
            rom_id=42,
            filename="pokemon.srm",
            resolution="upload",
            server_save_id=100,
            local_path=str(save_path),
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_invalid_resolution(self, tmp_path):
        svc, _ = make_service(tmp_path)
        result = await svc.resolve_conflict(rom_id=42, filename="x.srm", resolution="invalid", server_save_id=100)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_missing_server_save_id(self, tmp_path):
        svc, _ = make_service(tmp_path)
        result = await svc.resolve_conflict(rom_id=42, filename="x.srm", resolution="download")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_rom_not_installed(self, tmp_path):
        svc, _ = make_service(tmp_path)
        result = await svc.resolve_conflict(rom_id=999, filename="x.srm", resolution="download", server_save_id=100)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# TestSaveStatus
# ---------------------------------------------------------------------------


class TestSaveStatus:
    @pytest.mark.asyncio
    async def test_get_save_status(self, tmp_path):
        svc, fake = make_service(tmp_path)
        _install_rom(svc, tmp_path)
        _create_save(tmp_path)

        ss = _server_save()
        fake.saves[100] = ss

        result = await svc.get_save_status(42)
        assert result["rom_id"] == 42
        assert len(result["files"]) >= 1

    @pytest.mark.asyncio
    async def test_get_save_status_no_saves(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path)

        result = await svc.get_save_status(42)
        assert result["rom_id"] == 42
        assert result["files"] == []

    @pytest.mark.asyncio
    async def test_check_save_status_lightweight(self, tmp_path):
        svc, fake = make_service(tmp_path)
        _install_rom(svc, tmp_path)
        _create_save(tmp_path)

        ss = _server_save()
        fake.saves[100] = ss

        result = await svc.check_save_status_lightweight(42)
        assert result["rom_id"] == 42
        assert len(result["files"]) >= 1
        # Lightweight should not hash
        for f in result["files"]:
            assert f["local_hash"] is None


# ---------------------------------------------------------------------------
# TestSettings
# ---------------------------------------------------------------------------


class TestSettings:
    @pytest.mark.asyncio
    async def test_get_defaults(self, tmp_path):
        svc, _ = make_service(tmp_path)
        settings = await svc.get_save_sync_settings()
        assert settings["conflict_mode"] == "ask_me"
        assert settings["save_sync_enabled"] is False

    @pytest.mark.asyncio
    async def test_update_settings(self, tmp_path):
        svc, _ = make_service(tmp_path)
        result = await svc.update_save_sync_settings(
            {
                "save_sync_enabled": True,
                "conflict_mode": "newest_wins",
            }
        )
        assert result["success"] is True
        assert result["settings"]["save_sync_enabled"] is True
        assert result["settings"]["conflict_mode"] == "newest_wins"

    @pytest.mark.asyncio
    async def test_invalid_mode_ignored(self, tmp_path):
        svc, _ = make_service(tmp_path)
        await svc.update_save_sync_settings({"conflict_mode": "invalid_mode"})
        settings = await svc.get_save_sync_settings()
        assert settings["conflict_mode"] == "ask_me"

    @pytest.mark.asyncio
    async def test_unknown_key_ignored(self, tmp_path):
        svc, _ = make_service(tmp_path)
        result = await svc.update_save_sync_settings({"unknown_key": "value"})
        assert result["success"] is True
        assert "unknown_key" not in result["settings"]

    @pytest.mark.asyncio
    async def test_clock_skew_clamped(self, tmp_path):
        svc, _ = make_service(tmp_path)
        await svc.update_save_sync_settings({"clock_skew_tolerance_sec": -10})
        settings = await svc.get_save_sync_settings()
        assert settings["clock_skew_tolerance_sec"] == 0


# ---------------------------------------------------------------------------
# TestDeleteSaves
# ---------------------------------------------------------------------------


class TestDeleteSaves:
    @pytest.mark.asyncio
    async def test_delete_local_saves(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path)
        save_path = _create_save(tmp_path)
        assert save_path.exists()

        svc._save_sync_state["saves"]["42"] = {"files": {"pokemon.srm": {}}}

        result = await svc.delete_local_saves(42)
        assert result["success"] is True
        assert result["deleted_count"] == 1
        assert not save_path.exists()
        assert "42" not in svc._save_sync_state["saves"]

    @pytest.mark.asyncio
    async def test_delete_no_saves(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path)

        result = await svc.delete_local_saves(42)
        assert result["success"] is True
        assert result["deleted_count"] == 0

    @pytest.mark.asyncio
    async def test_delete_platform_saves(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path, rom_id=1, system="gba", file_name="game1.gba")
        _install_rom(svc, tmp_path, rom_id=2, system="gba", file_name="game2.gba")
        _create_save(tmp_path, system="gba", rom_name="game1")
        _create_save(tmp_path, system="gba", rom_name="game2")

        result = await svc.delete_platform_saves("gba")
        assert result["success"] is True
        assert result["deleted_count"] == 2

    @pytest.mark.asyncio
    async def test_delete_platform_saves_other_platform_untouched(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path, rom_id=1, system="gba", file_name="game1.gba")
        _install_rom(svc, tmp_path, rom_id=2, system="snes", file_name="game2.sfc")
        _create_save(tmp_path, system="gba", rom_name="game1")
        snes_save = _create_save(tmp_path, system="snes", rom_name="game2")

        await svc.delete_platform_saves("gba")
        assert snes_save.exists()
